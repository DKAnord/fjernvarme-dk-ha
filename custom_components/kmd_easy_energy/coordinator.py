"""Coordinator with full dashboard dataset, incremental cache, multi-unit support & Open-Meteo HDD."""

from __future__ import annotations

import asyncio
import calendar
import datetime as dt_mod
import logging
import math
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api.eforsyning_client import EforsyningClient, EforsyningLoginError
from .api.kmd_client import KMDClient
from .api.kmd_mitid_auth import KMDMitIDAuthenticator
from .const import (
    BACKEND_EFORSYNING,
    BACKEND_KMD,
    BACKENDS,
    CONF_AUTO_SYNC,
    CONF_AUTO_SYNC_HOUR,
    CONF_BACKEND,
    CONF_BONUS_TEMP,
    CONF_EF_INSTALLATION_ID,
    CONF_EF_PASSWORD,
    CONF_EF_SUPPLIER_ID,
    CONF_EF_USERNAME,
    CONF_CUSTOMER_ID,
    CONF_CUSTOMER_NUMBER,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_LOCATION_NAME,
    CONF_MITID_USERNAME,
    CONF_NOTIFY_SERVICE,
    CONF_PENALTY_TEMP,
    CONF_PORTAL_URL,
    CONF_SYNC_REMINDER,
    CONF_UTILITY,
    CONF_UTILITY_ID,
    CONF_UTILITY_STATUS,
    DEFAULT_AUTO_SYNC,
    DEFAULT_AUTO_SYNC_HOUR,
    DEFAULT_SYNC_REMINDER,
    DEFAULT_SYNC_REMINDER_BY_BACKEND,
    DOMAIN,
    EVENT_MITID_CHALLENGE,
    FIRST_SYNC_BACKFILL_MONTHS,
    SIGNAL_MITID_CHALLENGE,
    SYNC_BACKFILL_MONTHS,
    UPDATE_INTERVAL,
)
from .capabilities import backend_capabilities, effective_capabilities
from .eforsyning_mapping import apply_eforsyning_data
from .insights import (
    compact_hourly_point,
    copenhagen_today,
    daily_hdd_from_temps,
    daily_kwh_from_history,
    detect_abnormal_consumption,
    forecast_annual,
    kwh_per_hdd,
    last_local_day,
    merge_hourly_points,
    motivation_dkk_per_kwh,
    motivation_status,
)
from .statistics import import_hourly_statistics
from .sync_reminder import compute_sync_reminder, parse_last_sync
from .tariff import load_utilities, resolve_tariff
from .util import (
    cache_has_sensor_data,
    delete_legacy_www_cache,
    legacy_www_cache_paths,
    read_legacy_www_cache,
    sanitize_cache,
    store_for,
)


_LOGGER = logging.getLogger(__name__)

HDD_BASE = 17.0  # °C – common Danish district heating base

M_KEYS = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]
M_FULL = [
    "Januar", "Februar", "Marts", "April", "Maj", "Juni",
    "Juli", "August", "September", "Oktober", "November", "December",
]


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _compute_weather_and_insights(
    state: dict[str, Any], daily_temp: dict[str, float]
) -> dict[str, Any]:
    """Compute monthly/daily temp, R², baseload, and kWh/HDD17 from archive temps."""
    if not daily_temp:
        return {"weather": state.get("weather") or {}, "insights": state.get("insights") or {}}

    mon_t: dict[str, list[float]] = {}
    mon_hdd: dict[str, float] = {}
    for d, t in daily_temp.items():
        ym = d[:7]
        mon_t.setdefault(ym, []).append(t)
        mon_hdd[ym] = mon_hdd.get(ym, 0.0) + max(0.0, HDD_BASE - t)

    monthly_avg_t = {ym: round(sum(vs) / len(vs), 1) for ym, vs in sorted(mon_t.items())}
    cur_yr = str(copenhagen_today().year)
    prev_yr = str(copenhagen_today().year - 1)
    compact_m_temp = {
        ym: v
        for ym, v in monthly_avg_t.items()
        if ym.startswith((prev_yr + "-", cur_yr + "-"))
    }
    recent_d_temp = dict(sorted(daily_temp.items())[-120:])
    weather = {"monthly_temp": compact_m_temp, "daily_temp": recent_d_temp}

    pairs: list[tuple[float, float]] = []
    summer_vals: list[float] = []
    yr_totals: dict[str, dict[str, Any]] = {}
    cur_ym = copenhagen_today().strftime("%Y-%m")
    for y, mmap in (state.get("monthly") or {}).items():
        if not isinstance(mmap, dict):
            continue
        yr_totals[y] = {"kwh": 0.0, "hdd": 0.0, "months": 0}
        for idx, mk in enumerate(M_KEYS, 1):
            val = mmap.get(mk)
            if isinstance(val, (int, float)):
                ym = f"{y}-{idx:02d}"
                if ym in monthly_avg_t and ym != cur_ym:
                    kwh = float(val)
                    pairs.append((monthly_avg_t[ym], kwh))
                    if idx in (7, 8):
                        summer_vals.append(kwh)
                    yr_totals[y]["kwh"] += kwh
                    yr_totals[y]["hdd"] += mon_hdd.get(ym, 0.0)
                    yr_totals[y]["months"] += 1

    r2: float | None = None
    if len(pairs) > 5:
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        denom = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        if denom > 0:
            r = sum((x - mx) * (y - my) for x, y in pairs) / denom
            r2 = round(r * r * 100, 1)

    baseload = round(sum(summer_vals) / len(summer_vals), 1) if summer_vals else 124.0
    kwh_per_hdd: dict[str, float] = {}
    for y, st in sorted(yr_totals.items()):
        if st["hdd"] > 0 and st["months"] >= 6:
            space = max(0.0, st["kwh"] - baseload * st["months"])
            kwh_per_hdd[y] = round(space / st["hdd"], 2)

    insights = {
        "temp_r2_pct": r2,
        "baseload_kwh_mo": baseload,
        "kwh_per_hdd": kwh_per_hdd,
    }
    return {"weather": weather, "insights": insights}



def date_offset_months(day: dt_mod.date, months: int) -> dt_mod.date:
    """Shift a date by a whole number of months, keeping day=1 for the result."""
    year = day.year
    month = day.month + months
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return dt_mod.date(year, month, 1)




class KMDLoginError(RuntimeError):
    """KMD rejected the freshly issued MitID token (a real login failure)."""


class KMDEasyEnergyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Session-based coordinator.

    There is no background polling against KMD: ``_async_update_data`` only
    re-reads the private cache. Each user sync is one MitID login, a fetch of
    everything since the last sync (plus Energy statistics import), after which
    the short-lived access token is discarded and never persisted.
    """

    # Class-level defaults (also used by tests that bypass __init__).
    backend: str = BACKEND_KMD
    started_auto_sync_signature: tuple[bool, int] | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        portal_url: str = "https://minvarme.kredslob.dk/",
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.entry = entry
        self._portal_url = portal_url
        # Only set for the duration of one sync; never persisted.
        self.client: KMDClient | None = None
        self.last_sync: datetime | None = None
        self._reminder_sig: tuple[Any, ...] | None = None
        utility_id = str(entry.data.get(CONF_UTILITY_ID, "kredslob")).strip() or "kredslob"
        self._utility_id = utility_id
        self._store = store_for(hass, entry.entry_id)
        self._legacy_paths = legacy_www_cache_paths(hass, utility_id)
        self._initial_setup_complete: bool | None = None
        self.sync_state: str = "idle"
        self.sync_message: str = ""
        self.mitid_otp_code: str | None = None
        self.mitid_qr_svg: str | None = None
        self.mitid_qr_frames: list[str] = []
        self._sync_task: asyncio.Task[None] | None = None
        backend = str(entry.data.get(CONF_BACKEND) or BACKEND_KMD).strip().lower()
        self.backend: str = backend if backend in BACKENDS else BACKEND_KMD
        self.started_auto_sync_signature: tuple[bool, int] | None = None

    def _make_client(
        self,
        access_token: str,
        customer_id: str | None = None,
        customer_number: str | None = None,
    ) -> KMDClient:
        """Build a one-sync KMD client. The token lives only in this object."""
        customer_id = (
            customer_id
            or self.entry.data.get(CONF_CUSTOMER_ID)
            or self.entry.options.get(CONF_CUSTOMER_ID)
        )
        customer_number = (
            customer_number
            or self.entry.data.get(CONF_CUSTOMER_NUMBER)
            or self.entry.options.get(CONF_CUSTOMER_NUMBER)
        )
        return KMDClient(
            async_get_clientsession(self.hass),
            access_token,
            customer_id=customer_id,
            customer_number=customer_number,
            referer=self._portal_url,
        )

    @property
    def is_eforsyning(self) -> bool:
        return self.backend == BACKEND_EFORSYNING

    def _opt(self, key: str, default: Any = None) -> Any:
        value = self.entry.options.get(key)
        if value is None:
            value = self.entry.data.get(key, default)
        return value

    @property
    def sync_reminder_enabled(self) -> bool:
        default = DEFAULT_SYNC_REMINDER_BY_BACKEND.get(self.backend, DEFAULT_SYNC_REMINDER)
        return bool(self._opt(CONF_SYNC_REMINDER, default))

    @property
    def auto_sync_enabled(self) -> bool:
        """Automatic daily sync — only for backends that need no MitID."""
        return self.is_eforsyning and bool(self._opt(CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC))

    @property
    def backend_capabilities(self) -> frozenset[str]:
        """Static capabilities of this backend (decides which entities exist)."""
        return backend_capabilities(self.backend)

    def capabilities(self, state: dict[str, Any] | None = None) -> list[str]:
        """Backend capabilities that the cached data can actually fill."""
        return effective_capabilities(
            self.backend,
            self.data if state is None else state,
            reminder_enabled=self.sync_reminder_enabled,
            auto_sync_enabled=self.auto_sync_enabled,
        )

    @property
    def auto_sync_signature(self) -> tuple[bool, int]:
        return (self.auto_sync_enabled, self.auto_sync_hour)

    @property
    def auto_sync_hour(self) -> int:
        try:
            hour = int(self._opt(CONF_AUTO_SYNC_HOUR, DEFAULT_AUTO_SYNC_HOUR))
        except (TypeError, ValueError):
            hour = DEFAULT_AUTO_SYNC_HOUR
        return min(23, max(0, hour))

    def sync_reminder(self, now: datetime | None = None) -> dict[str, Any]:
        """Current soft-reminder attributes (computed locally, no KMD call)."""
        return compute_sync_reminder(
            self.last_sync, now or dt_util.utcnow(), self.sync_reminder_enabled
        )

    def _load_last_sync(self, state: dict[str, Any]) -> None:
        """Restore last sync time from cache (fallback: last fetch time ``updated``)."""
        parsed = parse_last_sync(state.get("last_sync"))
        if parsed is None and cache_has_sensor_data(state):
            parsed = parse_last_sync(state.get("updated"))
        if parsed is not None:
            self.last_sync = parsed

    @callback
    def async_start_reminder_timer(self) -> Callable[[], None]:
        """Re-evaluate the weekend reminder hourly (local only, no KMD call).

        Listeners are only updated when the reminder or the day count changes,
        so this costs at most a couple of state writes per day.
        """

        @callback
        def _tick(_now: datetime) -> None:
            self.async_refresh_reminder()

        return async_track_time_change(self.hass, _tick, minute=0, second=7)

    @callback
    def async_refresh_reminder(self) -> None:
        rem = self.sync_reminder()
        sig = (rem["sync_reminder"], rem["days_since_sync"], rem["sync_reminder_enabled"])
        if sig == self._reminder_sig:
            return
        self._reminder_sig = sig
        if self.data is not None:
            self.data = {**self.data, **rem}
            self.async_update_listeners()


    @property
    def has_usable_cache(self) -> bool:
        """Whether current/cached coordinator data can drive sensors."""
        return cache_has_sensor_data(self.data)

    async def async_initialize_cache(self) -> dict[str, Any]:
        """Load private store, migrate leftover www/ caches, and preload self.data."""
        state = await self._store.async_load()
        if not state:
            legacy = await self.hass.async_add_executor_job(
                read_legacy_www_cache, self._legacy_paths
            )
            if legacy:
                state = sanitize_cache(legacy)
                await self._store.async_save(state)
                await self.hass.async_add_executor_job(
                    delete_legacy_www_cache, self._legacy_paths
                )
            else:
                state = {}
                await self.hass.async_add_executor_job(
                    delete_legacy_www_cache, self._legacy_paths
                )
        state = sanitize_cache(state or {})
        self._load_last_sync(state)
        state.update(self._base_meta())
        if self._initial_setup_complete is None:
            self._initial_setup_complete = bool(
                state.get("initial_setup_complete", cache_has_sensor_data(state))
            )
        state["initial_setup_complete"] = self._initial_setup_complete
        self.data = state
        return state

    async def _async_load_cache(self) -> dict[str, Any]:
        if self.data:
            return dict(self.data)
        state = await self._store.async_load()
        return sanitize_cache(state or {})

    async def _async_save_cache(self, state: dict[str, Any]) -> None:
        await self._store.async_save(sanitize_cache(state))

    async def async_remove_storage(self) -> None:
        """Delete private store and any leftover public cache files."""
        await self._store.async_remove()
        await self.hass.async_add_executor_job(
            delete_legacy_www_cache, self._legacy_paths
        )

    def mitid_challenge_payload(self) -> dict[str, Any]:
        """Live MitID challenge for the card (contains the OTP / QR frames).

        Only delivered via the dispatcher signal + websocket subscription,
        never on the event bus (the recorder stores every bus event).
        """
        frames = list(getattr(self, "mitid_qr_frames", None) or [])
        if not frames and self.mitid_qr_svg:
            frames = [self.mitid_qr_svg]
        return {
            "entry_id": self.entry.entry_id,
            "utility_id": self._utility_id,
            "sync_state": self.sync_state,
            "sync_message": self.sync_message,
            "otp_code": self.mitid_otp_code,
            "qr_frames": frames,
        }

    def _fire_mitid_event(self) -> None:
        """Publish the MitID sync status (bus) and the live challenge (dispatcher)."""
        self.hass.bus.async_fire(
            EVENT_MITID_CHALLENGE,
            {
                "entry_id": self.entry.entry_id,
                "utility_id": self._utility_id,
                "sync_state": self.sync_state,
                "sync_message": self.sync_message,
                "has_otp": bool(self.mitid_otp_code),
                "has_qr": bool(self.mitid_qr_svg or getattr(self, "mitid_qr_frames", None)),
            },
        )
        async_dispatcher_send(
            self.hass, SIGNAL_MITID_CHALLENGE, self.mitid_challenge_payload()
        )

    async def _fetch_open_meteo_7d(self, lat: float, lon: float) -> float | None:
        session = async_get_clientsession(self.hass)
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&daily=temperature_2m_mean"
            "&timezone=Europe/Copenhagen&past_days=7&forecast_days=1"
        )
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
        means = (data.get("daily") or {}).get("temperature_2m_mean") or []
        hdd = [max(0.0, HDD_BASE - t) for t in means if t is not None]
        return round(sum(hdd), 1) if hdd else None

    async def _fetch_open_meteo_archive(self, lat: float, lon: float) -> dict[str, float]:
        session = async_get_clientsession(self.hass)
        end_dt = (copenhagen_today() - dt_mod.timedelta(days=1)).isoformat()
        url = (
            "https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}"
            f"&start_date=2022-01-01&end_date={end_dt}"
            "&daily=temperature_2m_mean&timezone=Europe%2FCopenhagen"
        )
        async with session.get(url) as resp:
            resp.raise_for_status()
            meteo = await resp.json()
        daily = meteo.get("daily") or {}
        out: dict[str, float] = {}
        for d, t in zip(daily.get("time") or [], daily.get("temperature_2m_mean") or []):
            if t is not None:
                out[str(d)] = round(float(t), 1)
        return out

    def _base_meta(self) -> dict[str, Any]:
        location = (
            self.entry.options.get(CONF_LOCATION_NAME)
            or self.entry.data.get(CONF_LOCATION_NAME)
            or ""
        )
        mitid_user = str(
            self.entry.options.get(CONF_MITID_USERNAME)
            or self.entry.data.get(CONF_MITID_USERNAME)
            or ""
        ).strip()
        masked_user = (
            f"{mitid_user[:2]}***{mitid_user[-1]}"
            if len(mitid_user) >= 4
            else ("***" if mitid_user else "")
        )
        notify_svc = str(
            self.entry.options.get(CONF_NOTIFY_SERVICE)
            or self.entry.data.get(CONF_NOTIFY_SERVICE)
            or ""
        ).strip()
        return {
            "utility": self.entry.data.get(CONF_UTILITY) or self.entry.title or "KMD Easy Energy",
            "utility_id": self.entry.data.get(CONF_UTILITY_ID, "kredslob"),
            "utility_status": self.entry.data.get(CONF_UTILITY_STATUS, "confirmed"),
            "portal_url": self._portal_url,
            "location": location,
            "bonus_temp": float(
                self.entry.options.get(CONF_BONUS_TEMP)
                or self.entry.data.get(CONF_BONUS_TEMP)
                or 30.0
            ),
            "penalty_temp": float(
                self.entry.options.get(CONF_PENALTY_TEMP)
                or self.entry.data.get(CONF_PENALTY_TEMP)
                or 40.0
            ),
            "backend": self.backend,
            "data_source": "E|Forsyning" if self.is_eforsyning else "KMD Easy Energy",
            "auto_sync": self.auto_sync_enabled,
            "auto_sync_hour": self.auto_sync_hour if self.auto_sync_enabled else None,
            "has_mitid_username": bool(mitid_user),
            "mitid_username_masked": masked_user,
            "notify_service": notify_svc,
            "entry_id": self.entry.entry_id,
            "sync_state": self.sync_state,
            "sync_message": self.sync_message,
            **self.sync_reminder(),
        }


    async def _async_backfill_history(
        self,
        state: dict[str, Any],
        mp: dict[str, Any],
        kwh_unit: dict[str, Any] | None,
        m3_unit: dict[str, Any] | None,
        today: dt_mod.date,
        first_sync: bool = False,
    ) -> None:
        """Extend daily/hourly history during a sync.

        Daily series (ZoomLevel=2) for this year and last year are fetched at
        most once per Copenhagen day. Hourly history: the first sync backfills
        up to a full year; later syncs fill up to a few still-missing months.
        Months already present are never re-fetched, so repeated syncs the
        same day cost no extra history requests.
        """
        if not self.client:
            return
        inst = mp.get("InstallationId")
        point = mp.get("MeasurementPointId")
        if not inst or not point:
            return

        today_s = today.isoformat()
        if state.get("daily_history_fetched_on") != today_s and kwh_unit:
            history = dict(state.get("daily_kwh_history") or {})
            for year in (today.year - 1, today.year):
                raw = await self.client.get_consumption_timeseries(
                    inst,
                    point,
                    kwh_unit,
                    2,
                    datetime(year, 1, 1),
                    datetime(year, 12, 31),
                )
                series = raw.get("Series") or []
                rows = (series[0] or {}).get("Data") or [] if series else []
                for item in rows:
                    if not item.get("IsComplete") and not item.get("Value"):
                        continue
                    df = str(item.get("DateFrom") or "")[:10]
                    if len(df) == 10 and item.get("Value") is not None:
                        history[df] = float(item["Value"])
            state["daily_kwh_history"] = history
            state["daily_history_fetched_on"] = today_s

        existing = merge_hourly_points(state.get("hourly_kwh") or [])
        max_months = FIRST_SYNC_BACKFILL_MONTHS if first_sync else SYNC_BACKFILL_MONTHS
        covered_months: set[tuple[int, int]] = set()
        for item in existing:
            dt = None
            try:
                from .insights import parse_iso_dt, hour_start_local

                parsed = parse_iso_dt(str(item.get("DateFrom") or ""))
                if parsed:
                    loc = hour_start_local(parsed)
                    covered_months.add((loc.year, loc.month))
            except Exception:  # noqa: BLE001
                continue

        # Walk backwards from last month; fill up to two months not yet covered.
        cursor = (today.replace(day=1) - dt_mod.timedelta(days=1)).replace(day=1)
        end_limit = date_offset_months(today, -12)
        filled = 0
        while cursor >= end_limit and filled < max_months:
            key = (cursor.year, cursor.month)
            month_end = datetime(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1]) + timedelta(days=1)
            month_start = datetime(cursor.year, cursor.month, 1)
            if key not in covered_months:
                if kwh_unit:
                    series = await self.client.get_hourly_with_fallback(
                        inst, point, kwh_unit, month_start, month_end
                    )
                    state["hourly_kwh"] = merge_hourly_points(
                        state.get("hourly_kwh") or [],
                        [p for x in series if (p := compact_hourly_point(x))],
                    )
                if m3_unit:
                    series = await self.client.get_hourly_with_fallback(
                        inst, point, m3_unit, month_start, month_end
                    )
                    state["hourly_m3"] = merge_hourly_points(
                        state.get("hourly_m3") or [],
                        [p for x in series if (p := compact_hourly_point(x))],
                    )
                filled += 1
            cursor = (cursor - dt_mod.timedelta(days=1)).replace(day=1)
        state["hourly_backfill_fetched_on"] = today_s
        state["hourly_kwh_points"] = len(state.get("hourly_kwh") or [])

    def _enrich_derived(self, state: dict[str, Any]) -> None:
        """Attach tariff, motivation, forecast and leak flags to coordinator data."""
        from dataclasses import asdict

        tariff = resolve_tariff(self.entry)
        state["tariff"] = asdict(tariff)
        state["energy_price_dkk_per_kwh"] = tariff.price_dkk_per_kwh
        state["volume_price_dkk_per_m3"] = tariff.price_dkk_per_m3

        # Current return temperature: same rule as KMDReturnTempSensor
        return_temp: float | None = None
        if state.get("has_direct_temp"):
            series = state.get("hourly_temp") or []
            complete = [p for p in series if p.get("IsComplete") and p.get("Value") is not None]
            if complete:
                return_temp = float(complete[-1]["Value"])
        if return_temp is None and state.get("latest_reading"):
            latest_rt = (state.get("latest_reading") or {}).get("temp_return")
            if isinstance(latest_rt, (int, float)) and latest_rt > 0:
                return_temp = float(latest_rt)
        if return_temp is None:
            rt_ann = (state.get("return_temp") or {}).get("annual") or {}
            yr_s = str(copenhagen_today().year)
            if yr_s in rt_ann and rt_ann[yr_s] is not None:
                return_temp = float(rt_ann[yr_s])
        state["motivation_status"] = motivation_status(
            return_temp, tariff.bonus_temp, tariff.penalty_temp
        )
        state["motivation_dkk_per_kwh"] = motivation_dkk_per_kwh(
            return_temp,
            tariff.bonus_temp,
            tariff.penalty_temp,
            tariff.motivation_dkk_per_kwh_per_k,
        )

        today = copenhagen_today()
        daily_kwh = daily_kwh_from_history(
            state.get("daily_kwh_history"),
            (state.get("daily") or {}).get("days"),
            today.replace(day=1),
        )
        weather = state.get("weather") or {}
        daily_hdd = daily_hdd_from_temps(weather.get("daily_temp"))
        state["daily_hdd"] = {d.isoformat(): v for d, v in daily_hdd.items()}

        insights = dict(state.get("insights") or {})
        window_kwh_hdd = kwh_per_hdd(daily_kwh, daily_hdd, end=today - dt_mod.timedelta(days=1))
        yearly = insights.get("kwh_per_hdd") or {}
        if isinstance(yearly, dict) and yearly:
            # Prefer the latest complete-year figure when the short window is thin.
            latest_year = yearly.get(str(today.year)) or yearly.get(str(today.year - 1))
        else:
            latest_year = None
        kph = window_kwh_hdd or (float(latest_year) if latest_year is not None else None)
        ytd = (state.get("annual") or {}).get(str(today.year))
        if ytd is None:
            # Sum history for the current year when the annual map is empty.
            ytd_sum = sum(v for d, v in daily_kwh.items() if d.year == today.year)
            ytd = round(ytd_sum, 2) if ytd_sum else None
        forecast = forecast_annual(ytd, kph, tariff.normal_hdd_year, today)
        state["degree_day"] = forecast
        if forecast.get("forecast_annual_kwh") is not None and tariff.price_dkk_per_kwh:
            state["degree_day"]["forecast_annual_dkk"] = round(
                float(forecast["forecast_annual_kwh"]) * tariff.price_dkk_per_kwh, 0
            )

        # Leak/abnormal: last complete day (yesterday, or latest complete daily).
        target = today - dt_mod.timedelta(days=1)
        daily_obj = state.get("daily") or {}
        if daily_obj.get("latest_date") and daily_obj.get("latest_complete"):
            try:
                latest = dt_mod.date.fromisoformat(str(daily_obj["latest_date"])[:10])
                if latest < today:
                    target = latest
            except ValueError:
                pass
        state["abnormal_consumption"] = detect_abnormal_consumption(
            daily_kwh, daily_hdd, target
        )
        state["backend_capabilities"] = sorted(self.backend_capabilities)
        state["capabilities"] = self.capabilities(state)

    async def _async_update_data(self) -> dict[str, Any]:
        """Return cached data only. Never contacts KMD (no background polling).

        Used at start-up (restores sensors after an HA restart without any
        network call) and by the ``refresh`` service.
        """
        state = await self._async_load_cache()
        await self.hass.async_add_executor_job(load_utilities)
        self._load_last_sync(state)
        if self._initial_setup_complete is None:
            self._initial_setup_complete = bool(
                state.get("initial_setup_complete", cache_has_sensor_data(state))
            )
        state.pop("token_expired", None)
        state.update(self._base_meta())
        state["initial_setup_complete"] = self._initial_setup_complete
        self._enrich_derived(state)
        return state

    async def _async_update_weather(self, state: dict[str, Any]) -> None:
        """Optional Open-Meteo 7-day HDD + archive insights (backend-independent)."""
        lat = (
            self.entry.options.get(CONF_LATITUDE)
            or self.entry.data.get(CONF_LATITUDE)
            or self.hass.config.latitude
        )
        lon = (
            self.entry.options.get(CONF_LONGITUDE)
            or self.entry.data.get(CONF_LONGITUDE)
            or self.hass.config.longitude
        )
        if lat is not None and lon is not None:
            today = copenhagen_today().isoformat()
            if state.get("weather_7d_fetched_on") == today and state.get("hdd_7d") is not None:
                _LOGGER.debug("Skipping Open-Meteo 7d (already fetched %s)", today)
            else:
                try:
                    state["hdd_7d"] = await self._fetch_open_meteo_7d(float(lat), float(lon))
                    state["weather_7d_fetched_on"] = today
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Optional Open-Meteo 7d failed: %s", err)
            if state.get("weather_archive_fetched_on") == today and state.get("weather"):
                _LOGGER.debug("Skipping Open-Meteo archive (already fetched %s)", today)
            else:
                try:
                    daily_temp = await self._fetch_open_meteo_archive(float(lat), float(lon))
                    computed = _compute_weather_and_insights(state, daily_temp)
                    state["weather"] = computed["weather"]
                    state["insights"] = computed["insights"]
                    state["weather_archive_fetched_on"] = today
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Optional Open-Meteo archive failed: %s", err)

    async def _async_fill_gap_since_last_sync(
        self,
        state: dict[str, Any],
        mp: dict[str, Any],
        kwh_unit: dict[str, Any] | None,
        m3_unit: dict[str, Any] | None,
        today: dt_mod.date,
    ) -> None:
        """Fetch hourly data from the last stored hour up to the current month.

        With sporadic (weekly) syncs the previous month's last days would
        otherwise be missing: the regular fetch covers the current month and
        the history backfill skips months that already have some points.
        """
        if not self.client:
            return
        inst = mp.get("InstallationId")
        point = mp.get("MeasurementPointId")
        if not inst or not point:
            return
        month_start = today.replace(day=1)
        oldest = date_offset_months(today, -12)
        for key, unit in (("hourly_kwh", kwh_unit), ("hourly_m3", m3_unit)):
            if not unit:
                continue
            points = state.get(key) or []
            last_day = last_local_day(points)
            if last_day is None or last_day >= month_start:
                continue
            start = max(last_day, oldest)  # re-fetch the last (maybe partial) day
            series = await self.client.get_hourly_with_fallback(
                inst,
                point,
                unit,
                datetime(start.year, start.month, start.day),
                datetime(month_start.year, month_start.month, month_start.day),
            )
            state[key] = merge_hourly_points(
                points, [p for x in series if (p := compact_hourly_point(x))]
            )

    async def _async_fetch_from_kmd(self, state: dict[str, Any]) -> dict[str, Any]:
        """Fetch everything since the last sync with the one-sync client."""
        if not self.client:
            raise RuntimeError("Intet KMD-login i denne synkronisering")
        first_sync = not (state.get("hourly_kwh") or [])
        try:
            meters = await self.client.get_active_meters()
            if not meters:
                state["meters"] = []
                state["available_units"] = []
                return state

            mp = meters[0]
            units = mp.get("Units") or []
            available_units = [
                {
                    "Id": u.get("Id"),
                    "Name": u.get("Name"),
                    "Description": u.get("Description"),
                    "Decimals": u.get("Decimals"),
                    "Order": u.get("Order"),
                }
                for u in units
                if isinstance(u, dict)
            ]
            _LOGGER.info("KMD meter[0] Units discovered: %s", available_units)

            kwh_unit = KMDClient.find_unit(units, "kWh") or (units[0] if units else None)
            m3_unit = KMDClient.find_unit(units, "m3") or KMDClient.find_unit(units, "m³")
            temp_unit = KMDClient.find_unit(units, "°C") or KMDClient.find_unit(units, "C")

            now_local = dt_util.now()
            yr = now_local.year
            mo = now_local.month
            last_dom = calendar.monthrange(yr, mo)[1]
            cph_tz = ZoneInfo("Europe/Copenhagen")

            state["meters"] = meters
            state["available_units"] = available_units
            state["has_direct_temp"] = bool(temp_unit)
            state["updated"] = now_local.isoformat(timespec="seconds")

            if kwh_unit:
                # 1. Monthly (ZoomLevel=1) for previous year + current year
                monthly_map = state.setdefault("monthly", {})
                annual_map = state.setdefault("annual", {})
                for target_yr in (yr - 1, yr):
                    yr_s = str(target_yr)
                    try:
                        m_raw = await self.client.get_consumption_timeseries(
                            mp["InstallationId"],
                            mp["MeasurementPointId"],
                            kwh_unit,
                            1,
                            datetime(target_yr, 1, 1),
                            datetime(target_yr, 12, 31),
                        )
                        s_list = m_raw.get("Series") or []
                        m_data = (s_list[0] or {}).get("Data") or [] if s_list else []
                        if m_data:
                            yr_dict = monthly_map.setdefault(yr_s, {})
                            for item in m_data:
                                df_str = item.get("DateFrom") or ""
                                if len(df_str) >= 7 and item.get("Value") is not None:
                                    m_idx = int(df_str[5:7])
                                    v = float(item["Value"])
                                    yr_dict[M_KEYS[m_idx - 1]] = int(v) if v.is_integer() else round(v, 2)
                            annual_map[yr_s] = round(
                                sum(v for v in yr_dict.values() if isinstance(v, (int, float)))
                            )
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning("Monthly fetch (%s) failed: %s", yr_s, err)

                # 2. Daily (ZoomLevel=2) for current month
                d_raw = await self.client.get_consumption_timeseries(
                    mp["InstallationId"],
                    mp["MeasurementPointId"],
                    kwh_unit,
                    2,
                    datetime(yr, mo, 1),
                    datetime(yr, mo, last_dom),
                )
                d_s_list = d_raw.get("Series") or []
                d_data = (d_s_list[0] or {}).get("Data") or [] if d_s_list else []
                days: dict[str, int | float] = {}
                complete_vals: list[int | float] = []
                complete_day_dts: list[datetime] = []
                latest_date: str | None = None
                latest_complete = False
                for item in d_data:
                    val = item.get("Value")
                    is_comp = bool(item.get("IsComplete"))
                    if is_comp or (val is not None and float(val) > 0):
                        df_str = item.get("DateFrom") or ""
                        if len(df_str) >= 10:
                            d_num = str(int(df_str[8:10]))
                            fv = float(val or 0)
                            num_v: int | float = int(fv) if fv.is_integer() else round(fv, 2)
                            days[d_num] = num_v
                            latest_date = df_str[:10]
                            latest_complete = is_comp
                            if is_comp:
                                complete_vals.append(num_v)
                                complete_day_dts.append(datetime.fromisoformat(latest_date))
                if days:
                    vals = list(days.values())
                    stat_vals = complete_vals or vals
                    history = dict(state.get("daily_kwh_history") or {})
                    for d_num, val in days.items():
                        try:
                            history[f"{yr}-{mo:02d}-{int(d_num):02d}"] = val
                        except (TypeError, ValueError):
                            continue
                    state["daily_kwh_history"] = history
                    state["daily"] = {
                        "month": f"{M_FULL[mo - 1]} {yr}",
                        "days": days,
                        "total": round(sum(vals), 2),
                        "gennemsnit": round(sum(stat_vals) / len(stat_vals), 1),
                        "minimum": min(stat_vals),
                        "maksimum": max(stat_vals),
                        "latest_date": latest_date,
                        "latest_complete": latest_complete,
                    }

                # 3. Hourly (ZoomLevel=3) across complete MTD days
                if complete_day_dts:
                    h_series = await self.client.get_hourly_with_fallback(
                        mp["InstallationId"],
                        mp["MeasurementPointId"],
                        kwh_unit,
                        complete_day_dts[0],
                        complete_day_dts[-1] + timedelta(days=1),
                    )
                    state["hourly_kwh_points"] = len(h_series)
                    state["hourly_kwh"] = merge_hourly_points(
                        state.get("hourly_kwh") or [],
                        [p for x in h_series if (p := compact_hourly_point(x))],
                    )
                    valid_day_isos = {d.date().isoformat() for d in complete_day_dts}
                    by_day: dict[str, dict[int, list[float]]] = {}
                    for x in h_series:
                        df_raw = x.get("DateFrom") or ""
                        if not df_raw:
                            continue
                        dt_obj = _parse_iso_dt(df_raw)
                        if not dt_obj:
                            continue
                        dt_loc = dt_obj.astimezone(cph_tz) if dt_obj.tzinfo else dt_obj.replace(tzinfo=cph_tz)
                        day_iso = dt_loc.date().isoformat()
                        if day_iso not in valid_day_isos:
                            continue
                        by_day.setdefault(day_iso, {}).setdefault(dt_loc.hour, []).append(
                            float(x.get("Value") or 0)
                        )
                    buckets: list[list[float]] = [[] for _ in range(24)]
                    n_days = 0
                    for day_hrs in by_day.values():
                        if len(day_hrs) < 23:
                            continue
                        hr_avgs = {hr_idx: sum(vals) / len(vals) for hr_idx, vals in day_hrs.items()}
                        nonzero_hrs = sum(1 for v in hr_avgs.values() if v > 0)
                        if nonzero_hrs >= 12:
                            n_days += 1
                            for hr_idx, val in hr_avgs.items():
                                if 0 <= hr_idx < 24:
                                    buckets[hr_idx].append(val)
                    if h_series:
                        raw_sample = [
                            (x.get("DateFrom"), x.get("Value"), x.get("IsComplete"))
                            for x in (h_series[:3] + (h_series[-3:] if len(h_series) > 3 else []))
                        ]
                    else:
                        raw_sample = []
                    if n_days >= 1 and all(buckets):
                        avg_24 = [round(sum(b) / len(b), 2) for b in buckets]
                        _LOGGER.info(
                            "KMD hourly MTD profile: n_days=%d, points=%d, sum(avg_24)=%.2f kWh/d vs daily_avg=%s, sample=%s, avg_24=%s",
                            n_days,
                            len(h_series),
                            sum(avg_24),
                            (state.get("daily") or {}).get("gennemsnit"),
                            raw_sample,
                            avg_24,
                        )
                        hr_obj = state.setdefault("hourly", {})
                        hr_obj["period"] = f"{M_KEYS[mo - 1].lower()}-{yr} MTD ({n_days} dage)"
                        hr_obj["days_averaged"] = n_days
                        hr_obj["kwh"] = avg_24
                    elif h_series:
                        _LOGGER.info(
                            "KMD hourly MTD skipped: n_days=%d, points=%d, sample=%s",
                            n_days,
                            len(h_series),
                            raw_sample,
                        )

            if m3_unit:
                start_mo = datetime(yr, mo, 1)
                m3_series = await self.client.get_hourly_with_fallback(
                    mp["InstallationId"], mp["MeasurementPointId"], m3_unit, start_mo, datetime(yr, mo, last_dom) + timedelta(days=1)
                )
                state["hourly_m3"] = merge_hourly_points(
                    state.get("hourly_m3") or [],
                    [p for x in m3_series if (p := compact_hourly_point(x))],
                )
            if temp_unit:
                start_mo = datetime(yr, mo, 1)
                state["hourly_temp"] = await self.client.get_hourly_with_fallback(
                    mp["InstallationId"], mp["MeasurementPointId"], temp_unit, start_mo, datetime(yr, mo, last_dom) + timedelta(days=1)
                )

            # 4. Settlement period + Forecast overview
            try:
                sp = await self.client.get_current_settlement_period()
                state["settlement_period"] = sp
                if kwh_unit and isinstance(sp, dict):
                    df = _parse_iso_dt(sp.get("DateFrom"))
                    dt_end = _parse_iso_dt(sp.get("DateTo"))
                    if df and dt_end:
                        ov = await self.client.get_consumption_overview(
                            mp["InstallationId"], mp["MeasurementPointId"], kwh_unit, df, dt_end
                        )
                        state["overview"] = ov
                        if ov.get("Actual") and ov.get("Expected"):
                            df_p = str(sp.get("DateFrom"))[:10].split("-")
                            dt_p = str(sp.get("DateTo"))[:10].split("-")
                            state["forecast"] = {
                                "period": f"{df_p[2]}.{df_p[1]}.{df_p[0]} - {dt_p[2]}.{dt_p[1]}.{dt_p[0]}",
                                "expected_kwh": round(float(ov["Actual"]["Value"])),
                                "budget_kwh": round(float(ov["Expected"]["Value"])),
                            }
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Optional settlement/overview failed: %s", err)

            # 5. Balance & Invoices
            try:
                bal = await self.client.get_balance()
                state["balance"] = bal
                bl_obj = state.setdefault("billing", {})
                if isinstance(bal, dict) and "Balance" in bal:
                    bl_obj["saldo_kr"] = round(float(bal["Balance"]), 2)
                stmt = await self.client.get_balance_statement(0, 10)
                invs = [x for x in stmt if x.get("Type") == "2" and (x.get("Amount") or 0) > 0]
                if invs:
                    latest = invs[0]
                    dt_p = str(latest["Date"])[:10].split("-")
                    bl_obj["last_bill_date"] = f"{dt_p[2]}.{dt_p[1]}.{dt_p[0]}"
                    bl_obj["last_bill_kr"] = round(float(latest["Amount"]), 2)
                    yr_sum = sum(float(x["Amount"]) for x in invs if str(x.get("Year")) == str(yr))
                    if yr_sum > 0:
                        bl_obj[f"total_{yr}_kr"] = round(yr_sum, 2)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Optional balance/statement failed: %s", err)

            # 6. Open-Meteo weather + insights
            await self._async_update_weather(state)

            try:
                await self._async_fill_gap_since_last_sync(
                    state, mp, kwh_unit, m3_unit, copenhagen_today(now_local)
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Optional gap fill since last sync failed: %s", err)
            try:
                await self._async_backfill_history(
                    state, mp, kwh_unit, m3_unit, copenhagen_today(now_local), first_sync
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Optional history backfill failed: %s", err)

            self._enrich_derived(state)
            try:
                imported = import_hourly_statistics(self.hass, self.entry, state)
                if imported["energy"] or imported["volume"]:
                    state["statistics_imported_on"] = copenhagen_today(now_local).isoformat()
                    state["statistics_imported"] = imported
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Optional Energy statistics import failed: %s", err)

            return state
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                raise KMDLoginError(
                    f"KMD afviste login (HTTP {err.status}) — prøv at synkronisere igen"
                ) from err
            raise RuntimeError(f"KMD API-fejl (HTTP {err.status})") from err

    async def async_sync_with_token(
        self,
        access_token: str,
        customer_id: str | None = None,
        customer_number: str | None = None,
    ) -> None:
        """Run one sync with a fresh access token, then discard the token.

        The token is only held by a temporary KMD client for the duration of
        this call. It is never written to the config entry or the cache.
        Statistics are imported idempotently (one row per hour, upserted), so
        several syncs the same day never create duplicates.
        """
        state = await self._async_load_cache()
        state.pop("token_expired", None)
        self.client = self._make_client(access_token, customer_id, customer_number)
        try:
            state = await self._async_fetch_from_kmd(state)
        finally:
            self.client = None
        self.last_sync = dt_util.utcnow()
        state["last_sync"] = self.last_sync.isoformat(timespec="seconds")
        self._initial_setup_complete = True
        state["initial_setup_complete"] = True
        state.update(self._base_meta())
        await self._async_save_cache(state)
        self._reminder_sig = None
        self.async_set_updated_data(state)

    async def async_update_token(
        self,
        access_token: str,
        customer_id: str | None = None,
        customer_number: str | None = None,
    ) -> None:
        """Backwards-compatible alias: one-shot sync with a pasted token (not stored)."""
        await self.async_sync_with_token(access_token, customer_id, customer_number)

    # ------------------------------------------------------------------
    # E|Forsyning backend (forbrugernummer + webpinkode, no MitID)
    # ------------------------------------------------------------------
    def _make_eforsyning_client(self) -> EforsyningClient:
        return EforsyningClient(
            async_get_clientsession(self.hass),
            str(self._opt(CONF_EF_USERNAME, "") or ""),
            str(self._opt(CONF_EF_PASSWORD, "") or ""),
            str(self._opt(CONF_EF_SUPPLIER_ID, "") or ""),
            self._opt(CONF_EF_INSTALLATION_ID),
        )

    async def async_sync_eforsyning(self) -> None:
        """One E|Forsyning sync: login -> daily readings -> map -> statistics.

        Raises KMDLoginError on rejected credentials (shown on the card, no
        reauth/repair) and RuntimeError on other failures. The cache is only
        written after a successful fetch, so a failure keeps the old values.
        """
        state = await self._async_load_cache()
        today = copenhagen_today()
        first_sync = not (state.get("daily_kwh_history") or {})
        client = self._make_eforsyning_client()
        try:
            fetched = await client.async_fetch(today, years_back=1 if first_sync else 0)
        except EforsyningLoginError as err:
            raise KMDLoginError(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise RuntimeError(str(err)[:160] or "E|Forsyning-fejl") from err
        finally:
            client.discard_credentials()
        apply_eforsyning_data(state, fetched, today)
        state["updated"] = dt_util.now().isoformat(timespec="seconds")
        await self._async_update_weather(state)
        self._enrich_derived(state)
        try:
            imported = import_hourly_statistics(self.hass, self.entry, state)
            if imported["energy"] or imported["volume"]:
                state["statistics_imported_on"] = today.isoformat()
                state["statistics_imported"] = imported
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Optional Energy statistics import failed: %s", err)
        self.last_sync = dt_util.utcnow()
        state["last_sync"] = self.last_sync.isoformat(timespec="seconds")
        self._initial_setup_complete = True
        state["initial_setup_complete"] = True
        state.update(self._base_meta())
        await self._async_save_cache(state)
        self._reminder_sig = None
        self.async_set_updated_data(state)

    async def _async_run_eforsyning_sync(self, automatic: bool = False) -> None:
        try:
            self._push_sync_ui("fetching_data", "Henter data fra E|Forsyning…")
            await self.async_sync_eforsyning()
            self._push_sync_ui("idle", "")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "E|Forsyning %s sync failed: %s", "automatic" if automatic else "manual", err
            )
            self._push_sync_ui("error", f"Fejl: {str(err)[:160]}")

    async def async_start_sync(self, automatic: bool = False) -> None:
        """Backend-independent "Synkroniser" (card, button, ``sync`` service)."""
        if not self.is_eforsyning:
            await self.async_start_mitid_sync()
            return
        if self._sync_task and not self._sync_task.done():
            _LOGGER.info("Sync already running")
            return
        self._sync_task = self.hass.async_create_task(
            self._async_run_eforsyning_sync(automatic)
        )

    @callback
    def async_start_auto_sync(self) -> Callable[[], None]:
        """Daily automatic sync for E|Forsyning (no-op for KMD/MitID).

        Runs at the configured hour (Europe/Copenhagen HA time) and once a few
        minutes after start-up when the last sync is older than a day.
        """
        self.started_auto_sync_signature = self.auto_sync_signature
        if not self.auto_sync_enabled:
            return lambda: None

        @callback
        def _daily(_now: datetime) -> None:
            self.hass.async_create_task(self.async_start_sync(automatic=True))

        unsub_daily = async_track_time_change(
            self.hass, _daily, hour=self.auto_sync_hour, minute=17, second=0
        )
        unsub_start: Callable[[], None] | None = None
        stale = self.last_sync is None or (dt_util.utcnow() - self.last_sync) > timedelta(hours=26)
        if stale:
            unsub_start = async_call_later(self.hass, 120, _daily)

        def _unsub() -> None:
            unsub_daily()
            if unsub_start:
                unsub_start()

        return _unsub

    async def async_set_setup_state(
        self, complete: bool, meta_updates: dict[str, Any] | None = None
    ) -> None:
        """Update initial setup state and/or utility metadata without losing cached data."""
        if meta_updates:
            data = dict(self.entry.data)
            data.update(meta_updates)
            if meta_updates.get(CONF_PORTAL_URL):
                self._portal_url = str(meta_updates[CONF_PORTAL_URL]).strip()
            if meta_updates.get(CONF_UTILITY_ID):
                self._utility_id = str(meta_updates[CONF_UTILITY_ID]).strip()
                self._legacy_paths = legacy_www_cache_paths(self.hass, self._utility_id)
            self.hass.config_entries.async_update_entry(self.entry, data=data)

        self._initial_setup_complete = complete
        if not complete:
            self.sync_state = "idle"
            self.sync_message = ""
            self.mitid_otp_code = None
            self.mitid_qr_svg = None
            self.mitid_qr_frames = []
        state = dict(self.data or await self._async_load_cache())
        state.update(self._base_meta())
        state["initial_setup_complete"] = complete
        await self._async_save_cache(state)
        self.async_set_updated_data(state)

    def _push_sync_ui(
        self,
        sync_state: str,
        sync_message: str,
        otp_code: str | None = None,
        qr_svg: str | None = None,
        qr_frames: list[str] | None = None,
        *,
        update_state: bool = True,
    ) -> None:
        self.sync_state = sync_state
        self.sync_message = sync_message
        self.mitid_otp_code = otp_code
        frames = [f for f in (qr_frames or []) if f]
        if not frames and qr_svg:
            frames = [qr_svg]
        self.mitid_qr_frames = frames
        self.mitid_qr_svg = frames[0] if frames else None
        if update_state:
            cur = dict(self.data or {})
            cur.update(self._base_meta())
            if self._initial_setup_complete is not None:
                cur["initial_setup_complete"] = self._initial_setup_complete
            self.async_set_updated_data(cur)
            self._fire_mitid_event()
        else:
            async_dispatcher_send(
                self.hass, SIGNAL_MITID_CHALLENGE, self.mitid_challenge_payload()
            )

    def _mitid_notification_id(self) -> str:
        return f"{DOMAIN}_mitid_{self.entry.entry_id}"

    async def _async_mitid_notification(self, message: str) -> None:
        """Show a transient persistent notification (code only in the body, not the title).

        Uses the helper directly instead of the ``persistent_notification.create``
        service: a service call fires a ``call_service`` bus event with the
        message, which the recorder would store.
        """
        try:
            persistent_notification.async_create(
                self.hass,
                message,
                title="MitID-godkendelse",
                notification_id=self._mitid_notification_id(),
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("persistent_notification create failed: %s", err)

    async def _async_dismiss_mitid_notification(self) -> None:
        try:
            persistent_notification.async_dismiss(self.hass, self._mitid_notification_id())
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("persistent_notification dismiss failed: %s", err)

    async def _async_notify(self, notify_svc: str, title: str, message: str) -> None:
        if not notify_svc:
            return
        svc = notify_svc.replace("notify.", "").strip()
        if not svc or not self.hass.services.has_service("notify", svc):
            return
        try:
            await self.hass.services.async_call(
                "notify",
                svc,
                {
                    "title": title,
                    "message": message,
                    "data": {"tag": "kmd-mitid", "priority": "high", "ttl": 0},
                },
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Optional notify.%s failed: %s", svc, err)

    async def async_start_mitid_sync(
        self,
        mitid_username: str | None = None,
        notify_service: str | None = None,
    ) -> None:
        """Start 100% pure-Python MitID + OIDC sync inside Home Assistant.

        For the E|Forsyning backend (no MitID) this starts a normal sync, so
        the existing button entity and service keep working.
        """
        if self.is_eforsyning:
            await self.async_start_sync()
            return
        if mitid_username is not None or notify_service is not None:
            data = dict(self.entry.data)
            if mitid_username and mitid_username.strip():
                data[CONF_MITID_USERNAME] = mitid_username.strip()
            if notify_service is not None:
                data[CONF_NOTIFY_SERVICE] = notify_service.strip()
            self.hass.config_entries.async_update_entry(self.entry, data=data)

        username = str(
            self.entry.options.get(CONF_MITID_USERNAME)
            or self.entry.data.get(CONF_MITID_USERNAME)
            or ""
        ).strip()
        if not username:
            self._push_sync_ui("error", "Fejl: Indtast dit MitID Bruger-ID først")
            return

        if self._sync_task and not self._sync_task.done():
            _LOGGER.info("MitID sync already running")
            return

        notify_svc = str(
            self.entry.options.get(CONF_NOTIFY_SERVICE)
            or self.entry.data.get(CONF_NOTIFY_SERVICE)
            or ""
        ).strip()
        self._sync_task = self.hass.async_create_task(
            self._async_run_mitid_flow(username, notify_svc)
        )

    async def _async_run_mitid_flow(self, username: str, notify_svc: str) -> None:
        auth = await self.hass.async_add_executor_job(KMDMitIDAuthenticator)
        util_name = str(self.entry.data.get(CONF_UTILITY) or self.entry.title or "KMD Easy Energy")
        try:
            self._push_sync_ui("starting", "Starter MitID-login (100% i Home Assistant)…")
            await self.hass.async_add_executor_job(auth.start_session, self._portal_url, username)

            self._push_sync_ui("waiting_app", "Åbn MitID-appen på din telefon og lås den op…")
            await self._async_notify(
                notify_svc,
                f"🔥 {util_name}",
                "Åbn MitID-appen på din telefon og lås den op for at godkende.",
            )

            otp_notified = False
            last_otp: str | None = None
            last_qr_frames: list[str] | None = None
            deadline = asyncio.get_running_loop().time() + 120
            while asyncio.get_running_loop().time() < deadline:
                t0 = asyncio.get_running_loop().time()
                res = await self.hass.async_add_executor_job(auth.poll_once)
                elapsed = asyncio.get_running_loop().time() - t0
                st = res.get("status")
                if st == "otp_ready" and res.get("otp_code"):
                    code = str(res["otp_code"])
                    if code != last_otp:
                        last_otp = code
                        last_qr_frames = None
                        self._push_sync_ui(
                            "otp_ready",
                            "Indtast 4-cifret kode i MitID-appen (se notifikation eller dashboard-kortet).",
                            otp_code=code,
                        )
                        await self._async_mitid_notification(
                            f"Indtast engangskoden {code} i MitID-appen og godkend."
                        )
                    if not otp_notified:
                        await self._async_notify(
                            notify_svc,
                            "🔑 MitID-kode klar",
                            f"Indtast de 4 cifre ({code}) i MitID-appen og godkend.",
                        )
                        otp_notified = True
                elif st == "qr_ready" and (res.get("qr_frames") or res.get("qr_svg")):
                    frames = [str(f) for f in (res.get("qr_frames") or [res["qr_svg"]]) if f]
                    if frames != last_qr_frames:
                        first_qr = last_qr_frames is None
                        last_qr_frames = frames
                        last_otp = None
                        self._push_sync_ui(
                            "qr_ready",
                            "Scan QR-koden på Fjernvarme-kortet med MitID-appen på din telefon.",
                            qr_frames=frames,
                            update_state=first_qr,
                        )
                        if first_qr:
                            await self._async_mitid_notification(
                                "Scan QR-koden på Fjernvarme-kortet med MitID-appen på din telefon. "
                                "Opsætter du på samme telefon som MitID-appen, så slå engangskoder "
                                "til i MitID-appen i stedet (se kortet)."
                            )
                elif st == "verified":
                    # QR scanned / code entered: no code needed any more, just wait
                    # for the user to approve in the MitID app.
                    if self.sync_state != "verified":
                        last_otp = None
                        last_qr_frames = None
                        self._push_sync_ui("verified", "Kode/QR godkendt — bekræft i MitID-appen…")
                        await self._async_mitid_notification(
                            "Kode/QR er godkendt — bekræft login i MitID-appen."
                        )
                elif st == "completed":
                    break
                elif st == "error":
                    raise RuntimeError(str(res.get("message") or "MitID afvist eller annulleret"))
                await asyncio.sleep(0.15 if elapsed < 0.2 else 0)
            else:
                raise RuntimeError("MitID timeout (120s) — prøv igen")

            self._push_sync_ui("fetching_data", "Godkendt — henter fjernvarmedata siden sidste synkronisering…")
            await self._async_dismiss_mitid_notification()
            access_token = await self.hass.async_add_executor_job(auth.finalize_and_exchange_token)
            try:
                await self.async_sync_with_token(access_token)
            finally:
                # Session-based: the token is used for this one sync only.
                access_token = ""
                auth = None
            self._push_sync_ui("idle", "")
            await self._async_notify(notify_svc, f"✅ {util_name} opdateret", "Fjernvarmedata er hentet.")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Native MitID sync failed: %s", err)
            self._push_sync_ui("error", f"Fejl: {str(err)[:160]}")
            await self._async_dismiss_mitid_notification()
            await self._async_notify(notify_svc, f"⚠️ {util_name} sync fejlede", str(err)[:160])

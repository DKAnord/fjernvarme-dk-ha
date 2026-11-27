"""Energy dashboard statistics import."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kmd_easy_energy.const import (
    CONF_FIXED_FEE_DKK_PER_YEAR,
    CONF_HEATED_AREA_M2,
    CONF_PRICE_DKK_PER_KWH,
    CONF_UTILITY_ID,
)
from kmd_easy_energy.statistics import (
    async_get_statistics_base_sums,
    build_cost_buckets,
    cost_statistic_id,
    energy_statistic_id,
    import_hourly_statistics,
    volume_statistic_id,
)


def test_statistic_ids() -> None:
    assert energy_statistic_id("abc") == "kmd_easy_energy:energy_abc"
    assert volume_statistic_id("abc") == "kmd_easy_energy:volume_abc"
    assert cost_statistic_id("abc") == "kmd_easy_energy:cost_abc"


def test_statistic_ids_normalize_uppercase_ulid() -> None:
    from homeassistant.components.recorder.statistics import valid_statistic_id

    ulid = "01M80451DZVEQJHQM9NP0W3ZBW"
    esid = energy_statistic_id(ulid)
    vsid = volume_statistic_id(ulid)
    csid = cost_statistic_id(ulid)
    assert esid == "kmd_easy_energy:energy_01m80451dzveqjhqm9np0w3zbw"
    assert vsid == "kmd_easy_energy:volume_01m80451dzveqjhqm9np0w3zbw"
    assert csid == "kmd_easy_energy:cost_01m80451dzveqjhqm9np0w3zbw"
    assert valid_statistic_id(esid)
    assert valid_statistic_id(vsid)
    assert valid_statistic_id(csid)
    assert valid_statistic_id(energy_statistic_id("Entry-With-Hyphens"))
    assert valid_statistic_id(cost_statistic_id("Entry-With-Hyphens"))


def test_import_skips_without_recorder() -> None:
    hass = MagicMock()
    hass.config.components = set()
    entry = SimpleNamespace(entry_id="e1", title="Kredsløb")
    result = import_hourly_statistics(
        hass,
        entry,
        {
            "hourly_kwh": [
                {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 1, "IsComplete": True}
            ]
        },
    )
    assert result == {"energy": 0, "volume": 0, "cost": 0}


def test_import_queues_external_statistics() -> None:
    hass = MagicMock()
    hass.config.components = {"recorder"}
    entry = SimpleNamespace(entry_id="e1", title="Kredsløb")
    state = {
        "hourly_kwh": [
            {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 1.0, "IsComplete": True},
            {"DateFrom": "2026-11-01T01:00:00.000Z", "Value": 2.0, "IsComplete": True},
        ],
        "hourly_m3": [
            {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 0.1, "IsComplete": True},
        ],
    }
    with patch(
        "homeassistant.components.recorder.statistics.async_add_external_statistics"
    ) as add:
        result = import_hourly_statistics(hass, entry, state)
    assert result == {"energy": 2, "volume": 1, "cost": 0}
    assert add.call_count == 2
    energy_meta = add.call_args_list[0].args[1]
    assert energy_meta["statistic_id"] == "kmd_easy_energy:energy_e1"
    assert energy_meta["source"] == "kmd_easy_energy"
    assert energy_meta["has_sum"] is True
    assert energy_meta["unit_class"] == "energy"
    rows = list(add.call_args_list[0].args[2])
    assert rows[-1]["sum"] == 3.0


def test_import_queues_external_statistics_with_cost_for_kredslob() -> None:
    from homeassistant.components.recorder.models.statistics import StatisticMeanType

    hass = MagicMock()
    hass.config.components = {"recorder"}
    entry = SimpleNamespace(
        entry_id="e1",
        title="Kredsløb",
        data={CONF_UTILITY_ID: "kredslob"},
        options={},
    )
    state = {
        "hourly_kwh": [
            {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 1.0, "IsComplete": True},
            {"DateFrom": "2026-11-01T01:00:00.000Z", "Value": 2.0, "IsComplete": True},
        ],
        "hourly_m3": [
            {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 0.1, "IsComplete": True},
        ],
    }
    with patch(
        "homeassistant.components.recorder.statistics.async_add_external_statistics"
    ) as add:
        result = import_hourly_statistics(hass, entry, state)
    assert result == {"energy": 2, "volume": 1, "cost": 2}
    assert add.call_count == 3
    cost_meta = add.call_args_list[2].args[1]
    assert cost_meta["statistic_id"] == "kmd_easy_energy:cost_e1"
    assert cost_meta["name"] == "Kredsløb cost"
    assert cost_meta["source"] == "kmd_easy_energy"
    assert cost_meta["unit_of_measurement"] == "DKK"
    assert cost_meta["unit_class"] is None
    assert cost_meta["has_sum"] is True
    assert cost_meta["mean_type"] == StatisticMeanType.NONE
    cost_rows = list(add.call_args_list[2].args[2])
    assert [r["state"] for r in cost_rows] == [0.668, 1.336]
    assert [r["sum"] for r in cost_rows] == [0.668, 2.004]


def test_cost_statistics_cross_year_and_effective_from_transitions() -> None:
    hass = MagicMock()
    hass.config.components = {"recorder"}

    kred_entry = SimpleNamespace(
        entry_id="k1",
        title="Kredsløb",
        data={CONF_UTILITY_ID: "kredslob"},
        options={},
    )
    kred_state = {
        "hourly_kwh": [
            {"DateFrom": "2026-12-31T11:00:00Z", "Value": 10.0, "IsComplete": True},
            {"DateFrom": "2027-01-01T11:00:00Z", "Value": 10.0, "IsComplete": True},
        ]
    }
    with patch(
        "homeassistant.components.recorder.statistics.async_add_external_statistics"
    ) as add:
        res = import_hourly_statistics(hass, kred_entry, kred_state, kinds=("cost",))
    assert res == {"energy": 0, "volume": 0, "cost": 2}
    rows = list(add.call_args_list[0].args[2])
    assert [r["state"] for r in rows] == [6.68, 7.175]
    assert [r["sum"] for r in rows] == [6.68, 13.855]

    silk_entry = SimpleNamespace(
        entry_id="s1",
        title="Silkeborg",
        data={CONF_UTILITY_ID: "silkeborg-forsyning"},
        options={},
    )
    silk_state = {
        "hourly_kwh": [
            {"DateFrom": "2027-01-31T11:00:00Z", "Value": 10.0, "IsComplete": True},
            {"DateFrom": "2027-02-01T11:00:00Z", "Value": 10.0, "IsComplete": True},
        ]
    }
    with patch(
        "homeassistant.components.recorder.statistics.async_add_external_statistics"
    ) as add:
        res = import_hourly_statistics(hass, silk_entry, silk_state, kinds=("cost",))
    assert res["cost"] == 2
    rows = list(add.call_args_list[0].args[2])
    assert [r["state"] for r in rows] == [8.55, 10.4]
    assert [r["sum"] for r in rows] == [8.55, 18.95]


def test_cost_statistics_pre_2026_history_falls_back_to_earliest_tariff() -> None:
    entry = SimpleNamespace(
        entry_id="k1",
        title="Kredsløb",
        data={CONF_UTILITY_ID: "kredslob"},
        options={},
    )
    buckets = [
        (datetime(2025, 12, 15, 12, 0, tzinfo=timezone.utc), 10.0),
        (datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc), 10.0),
    ]
    cost = build_cost_buckets(entry, {}, buckets)
    assert len(cost) == 2
    assert cost[0][1] == pytest.approx(6.68)
    assert cost[1][1] == pytest.approx(6.68)


def test_cost_statistics_motivation_monthly_dynamic_asymmetric_cap_and_fallback() -> None:
    # 1) Kredsløb monthly bonus/penalty + missing month fallback
    kred_entry = SimpleNamespace(
        entry_id="k1",
        title="Kredsløb",
        data={CONF_UTILITY_ID: "kredslob"},
        options={},
    )
    kred_state = {
        "return_temp": {"monthly_2026": {"Jan": 28.0, "Feb": 42.0, "Mar": 35.0}}
    }
    kred_buckets = [
        (datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # 28° -> 0.648
        (datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # 42° -> 0.688
        (datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # 35° -> 0.668
        (datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # missing -> 0.668
    ]
    assert [round(v, 5) for _, v in build_cost_buckets(kred_entry, kred_state, kred_buckets)] == [
        6.48,
        6.88,
        6.68,
        6.68,
    ]

    # 2) Hillerød penalty-only + dynamic forward temperature curve
    hil_entry = SimpleNamespace(
        entry_id="h1",
        title="Hillerød",
        data={CONF_UTILITY_ID: "hillerod-forsyning"},
        options={},
    )
    hil_state = {
        "return_temp": {
            "forward_monthly_2026": {"Jan": 58.0, "Feb": 68.0},
            "monthly_2026": {"Jan": 42.0, "Feb": 42.0},
        }
    }
    hil_buckets = [
        (datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # exp 47°, rt 42° -> no bonus -> 0.67
        (datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # exp 37°, rt 42° -> +5% -> 0.7035
    ]
    assert [round(v, 5) for _, v in build_cost_buckets(hil_entry, hil_state, hil_buckets)] == [
        6.7,
        7.035,
    ]

    # 3) Fixed DKK/kWh/K asymmetric rates in 2026 (synthetic utility)
    asym_utilities = [
        {
            "id": "synthetic-asym-varme",
            "tariffs": [
                {
                    "year": 2026,
                    "effective_from": "2026-01-01",
                    "price_dkk_per_kwh": 0.6925,
                    "motivation_dkk_per_kwh_per_k": 0.01076,
                    "motivation_bonus_dkk_per_kwh_per_k": 0.00538,
                    "bonus_temp": 41.0,
                    "penalty_temp": 41.0,
                }
            ],
        }
    ]
    asym_entry = SimpleNamespace(
        entry_id="asym",
        title="Asym",
        data={CONF_UTILITY_ID: "synthetic-asym-varme"},
        options={},
    )
    asym_state = {"return_temp": {"monthly_2026": {"Jan": 39.0, "Feb": 43.0}}}
    asym_buckets = [
        (datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # 0.6925 - 2*0.00538 = 0.68174
        (datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # 0.6925 + 2*0.01076 = 0.71402
    ]
    assert [
        round(v, 5)
        for _, v in build_cost_buckets(asym_entry, asym_state, asym_buckets, utilities=asym_utilities)
    ] == [
        6.8174,
        7.1402,
    ]

    # 4) Middelfart ±20 % cap
    mid_entry = SimpleNamespace(
        entry_id="mid",
        title="Middelfart",
        data={CONF_UTILITY_ID: "middelfart-fjernvarme"},
        options={},
    )
    mid_state = {"return_temp": {"monthly_2026": {"Jan": 10.0, "Feb": 65.0}}}
    mid_buckets = [
        (datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # 0.705 * 0.8 = 0.564
        (datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc), 10.0),  # 0.705 * 1.2 = 0.846
    ]
    assert [round(v, 5) for _, v in build_cost_buckets(mid_entry, mid_state, mid_buckets)] == [
        5.64,
        8.46,
    ]


def test_cost_statistics_excludes_fixed_fees_and_handles_custom_utility() -> None:
    silk_entry = SimpleNamespace(
        entry_id="s1",
        title="Silkeborg",
        data={CONF_UTILITY_ID: "silkeborg-forsyning"},
        options={CONF_HEATED_AREA_M2: 150.0, CONF_FIXED_FEE_DKK_PER_YEAR: 1100.0},
    )
    buckets = [(datetime(2027, 2, 1, 12, 0, tzinfo=timezone.utc), 10.0)]
    cost = build_cost_buckets(silk_entry, {}, buckets)
    assert cost[0][1] == pytest.approx(10.4)

    custom_no_price = SimpleNamespace(
        entry_id="c1",
        title="Custom",
        data={CONF_UTILITY_ID: "custom"},
        options={},
    )
    assert build_cost_buckets(custom_no_price, {}, buckets) == []

    custom_with_price = SimpleNamespace(
        entry_id="c2",
        title="Custom",
        data={CONF_UTILITY_ID: "custom"},
        options={CONF_PRICE_DKK_PER_KWH: 0.9},
    )
    assert build_cost_buckets(custom_with_price, {}, buckets)[0][1] == pytest.approx(9.0)


def test_cost_statistics_eforsyning_daily_buckets() -> None:
    from datetime import date
    from kmd_easy_energy.eforsyning_mapping import apply_eforsyning_data

    hass = MagicMock()
    hass.config.components = {"recorder"}
    readings = [
        {"date": "2026-11-02", "kwh": 25.0, "m3": 1.0, "temp_return": 37.0},
        {"date": "2026-11-03", "kwh": 30.0, "m3": 1.2, "temp_return": 37.0},
    ]
    state = apply_eforsyning_data({}, {"readings": readings}, date(2026, 11, 5))
    entry = SimpleNamespace(
        entry_id="ef1",
        title="Hjørring",
        data={CONF_UTILITY_ID: "hjorring-varmeforsyning"},
        options={},
    )
    with patch(
        "homeassistant.components.recorder.statistics.async_add_external_statistics"
    ) as add:
        res = import_hourly_statistics(hass, entry, state)
    assert res == {"energy": 2, "volume": 2, "cost": 2}
    cost_rows = list(add.call_args_list[2].args[2])
    assert cost_rows[0]["start"].hour == 0
    assert [r["state"] for r in cost_rows] == [12.65625, 15.1875]
    assert [r["sum"] for r in cost_rows] == [12.65625, 27.84375]


@pytest.mark.asyncio
async def test_base_sums_anchoring_and_kinds_filter() -> None:
    hass = MagicMock()
    hass.config.components = {"recorder"}
    entry = SimpleNamespace(
        entry_id="e1",
        title="Kredsløb",
        data={CONF_UTILITY_ID: "kredslob"},
        options={},
    )
    state = {
        "hourly_kwh": [
            {"DateFrom": "2026-11-01T00:00:00.000Z", "Value": 1.0, "IsComplete": True},
            {"DateFrom": "2026-11-01T01:00:00.000Z", "Value": 2.0, "IsComplete": True},
        ],
    }

    with patch(
        "homeassistant.components.recorder.statistics.async_add_external_statistics"
    ) as add:
        res = import_hourly_statistics(
            hass,
            entry,
            state,
            base_sums={"energy": 100.0, "cost": 66.8},
        )
    assert res == {"energy": 2, "volume": 0, "cost": 2}
    assert add.call_count == 2
    energy_rows = list(add.call_args_list[0].args[2])
    cost_rows = list(add.call_args_list[1].args[2])
    assert [r["sum"] for r in energy_rows] == [101.0, 103.0]
    assert [r["sum"] for r in cost_rows] == [67.468, 68.804]

    with patch(
        "homeassistant.components.recorder.statistics.async_add_external_statistics"
    ) as add:
        res = import_hourly_statistics(hass, entry, state, kinds=("cost",))
    assert res == {"energy": 0, "volume": 0, "cost": 2}
    assert add.call_count == 1
    assert add.call_args_list[0].args[1]["statistic_id"] == "kmd_easy_energy:cost_e1"

    # Without recorder -> {}
    no_rec_hass = MagicMock()
    no_rec_hass.config.components = set()
    assert await async_get_statistics_base_sums(no_rec_hass, entry, state) == {}

    # With recorder -> queries statistic_during_period strictly before first bucket
    recorder = SimpleNamespace(
        async_add_executor_job=AsyncMock(side_effect=lambda fn, *a: fn(*a))
    )

    def fake_stat_during_period(_hass, start_time, end_time, stat_id, types, units):
        assert start_time is None
        assert end_time == datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
        assert types == {"change"}
        assert units is None
        if stat_id == "kmd_easy_energy:energy_e1":
            return {"change": 100.0}
        if stat_id == "kmd_easy_energy:cost_e1":
            return {"change": 66.8}
        return {"change": None}

    with (
        patch("homeassistant.components.recorder.get_instance", return_value=recorder),
        patch(
            "homeassistant.components.recorder.statistics.statistic_during_period",
            side_effect=fake_stat_during_period,
        ),
    ):
        base = await async_get_statistics_base_sums(hass, entry, state)
    assert base == {"energy": 100.0, "cost": 66.8}

    # Recorder lookup failure returns {} gracefully
    with patch(
        "homeassistant.components.recorder.get_instance",
        side_effect=KeyError("missing"),
    ):
        assert await async_get_statistics_base_sums(hass, entry, state) == {}

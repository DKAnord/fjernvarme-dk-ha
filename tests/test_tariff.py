"""Published and option-overridden tariffs."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from kmd_easy_energy.tariff import published_tariff, resolve_tariff


KREDSLOB = [
    {
        "id": "kredslob",
        "tariffs": [
            {
                "year": 2026,
                "price_dkk_per_kwh": 0.668,
                "motivation_dkk_per_kwh_per_k": 0.01,
                "bonus_temp": 30.0,
                "penalty_temp": 40.0,
                "source": "https://www.kredslob.dk/privat/fjernvarme/fjernvarmepriser",
            },
            {
                "year": 2027,
                "price_dkk_per_kwh": 0.7175,
                "motivation_dkk_per_kwh_per_k": 0.01075,
                "source": "https://www.kredslob.dk/privat/fjernvarme/fjernvarmepriser",
            },
        ],
    }
]


def _entry(options=None, data=None):
    return SimpleNamespace(
        options=options or {},
        data=data or {"utility_id": "kredslob"},
    )


def test_published_kredslob_2026_and_2027() -> None:
    t26 = published_tariff("kredslob", 2026, KREDSLOB)
    t27 = published_tariff("kredslob", 2027, KREDSLOB)
    assert t26["price_dkk_per_kwh"] == 0.668
    assert t27["price_dkk_per_kwh"] == 0.7175
    assert published_tariff("unknown", 2026, KREDSLOB) is None


def test_resolve_uses_published_default_for_2026() -> None:
    tariff = resolve_tariff(_entry(), today=date(2026, 11, 22), utilities=KREDSLOB)
    assert tariff.price_dkk_per_kwh == 0.668
    assert tariff.motivation_dkk_per_kwh_per_k == 0.01
    assert tariff.bonus_temp == 30.0
    assert tariff.source and "kredslob.dk" in tariff.source
    # 0 in options means "use default"
    overridden = resolve_tariff(
        _entry(options={"price_dkk_per_kwh": 0.9, "normal_hdd_year": 2800}),
        today=date(2026, 11, 22),
        utilities=KREDSLOB,
    )
    assert overridden.price_dkk_per_kwh == 0.9
    assert overridden.normal_hdd_year == 2800
    zero = resolve_tariff(
        _entry(options={"price_dkk_per_kwh": 0}),
        today=date(2026, 11, 22),
        utilities=KREDSLOB,
    )
    assert zero.price_dkk_per_kwh == 0.668


def test_unknown_utility_has_no_invented_price() -> None:
    tariff = resolve_tariff(
        _entry(data={"utility_id": "custom"}),
        today=date(2026, 11, 22),
        utilities=KREDSLOB,
    )
    assert tariff.price_dkk_per_kwh is None
    assert tariff.price_dkk_per_m3 is None


def test_bundled_utilities_json_has_kredslob_tariffs() -> None:
    from kmd_easy_energy.tariff import load_utilities

    bundled = published_tariff("kredslob", 2026, load_utilities())
    assert bundled is not None
    assert bundled["price_dkk_per_kwh"] == 0.668
    assert bundled["source"].startswith("https://www.kredslob.dk/")
    # No guessed volume price — Kredsløb bills heat in kWh, not m³.
    assert not bundled.get("price_dkk_per_m3")


def test_bundled_utilities_json_has_soroe_2026_tariff() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    bundled = published_tariff("soroe-fjernvarme", 2026, utilities)
    assert bundled is not None
    assert bundled["price_dkk_per_kwh"] == 0.981
    assert bundled["motivation_pct_per_k"] == 1.0
    assert bundled["bonus_temp"] == 35.0
    assert bundled["penalty_temp"] == 45.0
    assert bundled["source"].startswith("https://www.affaldplus.dk/")
    assert not bundled.get("price_dkk_per_m3")

    resolved = resolve_tariff(
        _entry(data={"utility_id": "soroe-fjernvarme"}),
        today=date(2026, 11, 23),
        utilities=utilities,
    )
    assert resolved.price_dkk_per_kwh == 0.981
    assert resolved.motivation_pct_per_k == 1.0
    assert resolved.motivation_dkk_per_kwh_per_k == 0.00981
    assert resolved.bonus_temp == 35.0
    assert resolved.penalty_temp == 45.0

    overridden = resolve_tariff(
        _entry(options={"price_dkk_per_kwh": 1.2}, data={"utility_id": "soroe-fjernvarme"}),
        today=date(2026, 11, 23),
        utilities=utilities,
    )
    assert overridden.price_dkk_per_kwh == 1.2
    assert overridden.motivation_dkk_per_kwh_per_k == 0.012


def test_bundled_utilities_json_has_middelfart_2026_tariff_and_expected_return() -> None:
    from kmd_easy_energy.const import CONF_BONUS_TEMP, CONF_MOTIVATION_PCT_PER_K, CONF_PENALTY_TEMP, CONF_PRICE_DKK_PER_KWH
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    bundled = published_tariff("middelfart-fjernvarme", 2026, utilities)
    assert bundled is not None
    assert bundled["price_dkk_per_kwh"] == 0.705
    assert bundled["motivation_pct_per_k"] == 1.0
    assert bundled["motivation_max_pct"] == 20.0
    assert bundled["bonus_temp"] == 37.0 and bundled["penalty_temp"] == 37.0
    assert bundled["source"].startswith("https://middelfartfjernvarme.dk/")

    # When E|Forsyning reports Forv_Retur (e.g. 38.4 °C) and user options are 0/unset,
    # expected_return_temp overrides the static fallback (37.0 °C).
    resolved = resolve_tariff(
        _entry(options={CONF_BONUS_TEMP: 0.0, CONF_PENALTY_TEMP: 0.0}, data={"utility_id": "middelfart-fjernvarme"}),
        today=date(2026, 11, 23),
        utilities=utilities,
        expected_return_temp=38.4,
    )
    assert resolved.price_dkk_per_kwh == 0.705
    assert resolved.motivation_pct_per_k == 1.0
    assert resolved.motivation_max_pct == 20.0
    assert resolved.motivation_dkk_per_kwh_per_k == 0.00705
    assert resolved.bonus_temp == 38.4 and resolved.penalty_temp == 38.4

    # Explicit user options > 0 override E|Forsyning's Forv_Retur, and custom %/°C scales with price.
    explicit = resolve_tariff(
        _entry(
            options={
                CONF_PRICE_DKK_PER_KWH: 1.0,
                CONF_MOTIVATION_PCT_PER_K: 2.0,
                CONF_BONUS_TEMP: 35.0,
                CONF_PENALTY_TEMP: 35.0,
            },
            data={"utility_id": "middelfart-fjernvarme"},
        ),
        today=date(2026, 11, 23),
        utilities=utilities,
        expected_return_temp=38.4,
    )
    assert explicit.bonus_temp == 35.0 and explicit.penalty_temp == 35.0
    assert explicit.motivation_pct_per_k == 2.0
    assert explicit.motivation_dkk_per_kwh_per_k == 0.02

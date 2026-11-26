"""Published and option-overridden tariffs."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from kmd_easy_energy.tariff import (
    expected_return_from_forward_temp,
    published_tariff,
    resolve_tariff,
)


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


def test_bundled_utilities_json_has_hadsund_2026_tariff_and_custom_matching() -> None:
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    bundled = published_tariff("hadsund-fjernvarme", 2026, utilities)
    assert bundled is not None
    assert bundled["price_dkk_per_kwh"] == 0.62938
    assert bundled["motivation_pct_per_k"] == 2.0
    assert bundled["bonus_temp"] == 30.0
    assert bundled["penalty_temp"] == 40.0
    assert bundled["source"].startswith("https://hadsundfjernvarme.dk/")

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "49c73776-76be-4382-ba5c-2b4e7384cc34",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "hadsund-fjernvarme"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/hadsundfjernvarme",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "hadsund-fjernvarme"

    resolved = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "eforsyning_supplier_id": "49C73776-76BE-4382-BA5C-2B4E7384CC34",
                "portal_url": "https://eforsyning.dk/hadsundfjernvarme/",
            }
        ),
        today=date(2026, 11, 24),
        utilities=utilities,
    )
    assert resolved.utility_id == "hadsund-fjernvarme"
    assert resolved.price_dkk_per_kwh == 0.62938
    assert resolved.motivation_pct_per_k == 2.0
    assert resolved.motivation_dkk_per_kwh_per_k == round(0.62938 * 0.02, 6)
    assert resolved.bonus_temp == 30.0 and resolved.penalty_temp == 40.0


def test_bundled_utilities_json_has_fjernvarme_fyn_2026_tariff() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    bundled = published_tariff("fjernvarme-fyn", 2026, utilities)
    assert bundled is not None
    assert bundled["price_dkk_per_kwh"] == 0.5895
    assert bundled["source"].startswith("https://www.fjernvarmefyn.dk/")

    resolved = resolve_tariff(
        _entry(data={"utility_id": "fjernvarme-fyn"}),
        today=date(2026, 11, 24),
        utilities=utilities,
    )
    assert resolved.price_dkk_per_kwh == 0.5895


def test_bundled_utilities_json_has_beof_2026_tariff() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    assert by_id["beof"]["status"] == "confirmed"
    assert by_id["beof"]["tier"] == "confirmed"

    bundled = published_tariff("beof", 2026, utilities)
    assert bundled is not None
    assert bundled["price_dkk_per_kwh"] == 0.7275
    assert bundled["motivation_pct_per_k"] == 1.0
    assert bundled["source"] == "https://beof.dk/vores-varme/priser-og-gebyrer/"

    resolved = resolve_tariff(
        _entry(data={"utility_id": "beof"}),
        today=date(2026, 11, 24),
        utilities=utilities,
    )
    assert resolved.price_dkk_per_kwh == 0.7275
    assert resolved.motivation_pct_per_k == 1.0
    assert resolved.motivation_dkk_per_kwh_per_k == round(0.7275 * 0.01, 6)


def test_bundled_utilities_json_has_hedensted_and_hillerod_2026_tariffs() -> None:
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    assert by_id["hedensted-fjernvarme"]["status"] == "confirmed"
    assert by_id["hillerod-forsyning"]["status"] == "confirmed"

    hed_2026 = published_tariff("hedensted-fjernvarme", 2026, utilities)
    assert hed_2026 is not None
    assert hed_2026["price_dkk_per_kwh"] == 0.93125
    assert hed_2026["motivation_pct_per_k"] == 2.0
    assert hed_2026["bonus_temp"] == 40.0
    assert hed_2026["penalty_temp"] == 40.0
    assert hed_2026["source"].startswith("https://hedensted-fjernvarme.dk/")

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "4f2200af-8833-4237-81d9-e5cef34582a2",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "hedensted-fjernvarme"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/hedenstedfjernvarme",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "hedensted-fjernvarme"

    hed_resolved = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://eforsyning.dk/hedenstedfjernvarme/",
            }
        ),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert hed_resolved.utility_id == "hedensted-fjernvarme"
    assert hed_resolved.price_dkk_per_kwh == 0.93125
    assert hed_resolved.motivation_pct_per_k == 2.0
    assert hed_resolved.motivation_dkk_per_kwh_per_k == round(0.93125 * 0.02, 6)

    hil_2026 = published_tariff("hillerod-forsyning", 2026, utilities)
    assert hil_2026 is not None
    assert hil_2026["price_dkk_per_kwh"] == 0.67
    assert hil_2026["motivation_pct_per_k"] == 1.0
    assert hil_2026["motivation_bonus"] is False
    assert hil_2026["bonus_temp"] == 0.0
    assert hil_2026["penalty_temp"] == 40.0
    assert hil_2026["expected_return_by_forward_temp"] == [[58.0, 47.0], [68.0, 37.0]]
    assert hil_2026["source"].startswith("https://hfors.dk/")

    hil_resolved = resolve_tariff(
        _entry(data={"utility_id": "hillerod-forsyning"}),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert hil_resolved.price_dkk_per_kwh == 0.67
    assert hil_resolved.motivation_pct_per_k == 1.0
    assert hil_resolved.motivation_dkk_per_kwh_per_k == round(0.67 * 0.01, 6)
    assert hil_resolved.motivation_bonus is False
    assert hil_resolved.bonus_temp == 0.0
    assert hil_resolved.penalty_temp == 40.0
    assert hil_resolved.forward_temp is None
    assert hil_resolved.forward_temp_source is None


def test_bundled_utilities_json_has_frederikshavn_2026_tariff() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    assert by_id["frederikshavn-forsyning"]["status"] == "confirmed"
    assert by_id["frederikshavn-forsyning"]["tier"] == "confirmed"

    bundled = published_tariff("frederikshavn-forsyning", 2026, utilities)
    assert bundled is not None
    assert bundled["price_dkk_per_kwh"] == 0.87375
    assert bundled["motivation_pct_per_k"] == 1.0
    assert bundled["source"] == "https://www.forsyningen.dk/varme/priser"

    resolved = resolve_tariff(
        _entry(data={"utility_id": "frederikshavn-forsyning"}),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert resolved.price_dkk_per_kwh == 0.87375
    assert resolved.motivation_pct_per_k == 1.0
    assert resolved.motivation_dkk_per_kwh_per_k == round(0.87375 * 0.01, 6)

    hil_2027 = published_tariff("hillerod-forsyning", 2027, utilities)
    assert hil_2027 is not None and hil_2027["price_dkk_per_kwh"] == 0.75


def test_hillerod_dynamic_forward_temp_curve_and_overrides() -> None:
    from kmd_easy_energy.const import CONF_BONUS_TEMP, CONF_FORWARD_TEMP
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    curve = [[58.0, 47.0], [68.0, 37.0]]
    assert expected_return_from_forward_temp(55.0, curve) == 47.0
    assert expected_return_from_forward_temp(58.0, curve) == 47.0
    assert expected_return_from_forward_temp(60.0, curve) == 45.0
    assert expected_return_from_forward_temp(65.0, curve) == 40.0
    assert expected_return_from_forward_temp(68.0, curve) == 37.0
    assert expected_return_from_forward_temp(80.0, curve) == 37.0
    assert expected_return_from_forward_temp(None, curve) is None

    # Meter forward temp 55 °C -> penalty_temp 47.0 °C, penalty-only (bonus_temp=0.0).
    meter = resolve_tariff(
        _entry(data={"utility_id": "hillerod-forsyning"}),
        today=date(2026, 11, 25),
        utilities=utilities,
        forward_temp=55.0,
    )
    assert meter.motivation_bonus is False
    assert meter.bonus_temp == 0.0
    assert meter.penalty_temp == 47.0
    assert meter.forward_temp == 55.0
    assert meter.forward_temp_source == "meter"

    # Manual forward_temp option overrides meter forward_temp.
    manual_fwd = resolve_tariff(
        _entry(
            options={CONF_FORWARD_TEMP: 80.0},
            data={"utility_id": "hillerod-forsyning"},
        ),
        today=date(2026, 11, 25),
        utilities=utilities,
        forward_temp=55.0,
    )
    assert manual_fwd.motivation_bonus is False
    assert manual_fwd.bonus_temp == 0.0
    assert manual_fwd.penalty_temp == 37.0
    assert manual_fwd.forward_temp == 80.0
    assert manual_fwd.forward_temp_source == "manual"

    # Explicit bonus_temp > 0 re-enables bonus if a user explicitly configures it.
    explicit_bonus = resolve_tariff(
        _entry(
            options={CONF_BONUS_TEMP: 32.0},
            data={"utility_id": "hillerod-forsyning"},
        ),
        today=date(2026, 11, 25),
        utilities=utilities,
        forward_temp=65.0,
    )
    assert explicit_bonus.motivation_bonus is True
    assert explicit_bonus.bonus_temp == 32.0
    assert explicit_bonus.penalty_temp == 40.0


def test_fixed_subscription_fee_area_and_flat_resolution() -> None:
    from kmd_easy_energy.const import (
        CONF_FIXED_FEE_DKK_PER_M2_YEAR,
        CONF_FIXED_FEE_DKK_PER_YEAR,
        CONF_HEATED_AREA_M2,
    )
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    hed_2026 = published_tariff("hedensted-fjernvarme", 2026, utilities)
    assert hed_2026 is not None
    assert hed_2026["fixed_fee_dkk_per_m2_year"] == 33.75

    # Without heated_area_m2, annual_fixed_fee_dkk stays 0.0 (no change for existing users).
    no_area = resolve_tariff(
        _entry(data={"utility_id": "hedensted-fjernvarme"}),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert no_area.fixed_fee_dkk_per_m2_year == 33.75
    assert no_area.heated_area_m2 is None
    assert no_area.annual_fixed_fee_dkk == 0.0

    # With heated_area_m2=162, uses Hedensted's bundled 33.75 DKK/m²/year -> 5467.50 DKK/year.
    with_area = resolve_tariff(
        _entry(
            options={CONF_HEATED_AREA_M2: 162.0},
            data={"utility_id": "hedensted-fjernvarme"},
        ),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert with_area.heated_area_m2 == 162.0
    assert with_area.annual_fixed_fee_dkk == 5467.5

    # Custom area fee override (e.g. 33.25 excl. VAT + 25% = 41.5625) + optional flat meter fee.
    custom_override = resolve_tariff(
        _entry(
            options={
                CONF_FIXED_FEE_DKK_PER_M2_YEAR: 41.5625,
                CONF_HEATED_AREA_M2: 162.0,
            },
            data={"utility_id": "hedensted-fjernvarme"},
        ),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert custom_override.annual_fixed_fee_dkk == round(41.5625 * 162.0, 2)

    with_flat = resolve_tariff(
        _entry(
            options={
                CONF_FIXED_FEE_DKK_PER_M2_YEAR: 41.5625,
                CONF_HEATED_AREA_M2: 162.0,
                CONF_FIXED_FEE_DKK_PER_YEAR: 787.5,
            },
            data={"utility_id": "hedensted-fjernvarme"},
        ),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert with_flat.fixed_fee_dkk_per_year == 787.5
    assert with_flat.annual_fixed_fee_dkk == round(41.5625 * 162.0 + 787.5, 2)


def test_bundled_utilities_json_has_dronninglund_2026_tariff_and_custom_matching() -> None:
    from kmd_easy_energy.const import CONF_HEATED_AREA_M2
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    assert by_id["dronninglund-fjernvarme"]["status"] == "confirmed"
    assert by_id["dronninglund-fjernvarme"]["tier"] == "confirmed"

    dron_2026 = published_tariff("dronninglund-fjernvarme", 2026, utilities)
    assert dron_2026 is not None
    assert dron_2026["price_dkk_per_kwh"] == 0.81875
    assert dron_2026["fixed_fee_dkk_per_m2_year"] == 25.0
    assert dron_2026["motivation_pct_per_k"] == 1.0
    assert dron_2026["bonus_temp"] == 30.0
    assert dron_2026["penalty_temp"] == 40.0
    assert dron_2026["source"].startswith("https://dronninglundfjernvarme.dk/")

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "66d241dc-ae10-49f5-a176-81cc8c58bef7",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "dronninglund-fjernvarme"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/dronninglundfjernvarme",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "dronninglund-fjernvarme"

    resolved = resolve_tariff(
        _entry(
            options={CONF_HEATED_AREA_M2: 140.0},
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://eforsyning.dk/dronninglundfjernvarme/",
            },
        ),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert resolved.utility_id == "dronninglund-fjernvarme"
    assert resolved.price_dkk_per_kwh == 0.81875
    assert resolved.fixed_fee_dkk_per_m2_year == 25.0
    assert resolved.annual_fixed_fee_dkk == 3500.0
    assert resolved.motivation_pct_per_k == 1.0
    assert resolved.motivation_dkk_per_kwh_per_k == round(0.81875 * 0.01, 6)


def test_bundled_utilities_2026_tariffs_and_non_heating_cleanup() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}

    # Non-district-heating utilities removed.
    for removed in ("lef", "provas", "skanderborg-forsyning", "samn", "go-energi"):
        assert removed not in by_id

    # Spot-check newly populated 2026/2027 tariffs and resolution.
    aalborg = resolve_tariff(
        _entry(data={"utility_id": "aalborg-forsyning"}),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert aalborg.price_dkk_per_kwh == 0.95625
    assert aalborg.fixed_fee_dkk_per_m2_year == 14.0
    assert aalborg.motivation_pct_per_k == 2.0

    egedal_2026 = resolve_tariff(
        _entry(data={"utility_id": "egedal-fjernvarme"}),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert egedal_2026.price_dkk_per_kwh == 0.54625
    assert egedal_2026.fixed_fee_dkk_per_m2_year == 26.25
    assert egedal_2026.motivation_bonus is False
    assert egedal_2026.penalty_temp == 37.0

    egedal_2027 = resolve_tariff(
        _entry(data={"utility_id": "egedal-fjernvarme"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert egedal_2027.fixed_fee_dkk_per_m2_year == 33.125

    fredericia = resolve_tariff(
        _entry(data={"utility_id": "fredericia-fjernvarme"}),
        today=date(2026, 11, 25),
        utilities=utilities,
    )
    assert fredericia.price_dkk_per_kwh == 0.4185
    assert fredericia.price_dkk_per_m3 == 3.0
    assert fredericia.fixed_fee_dkk_per_m2_year == 34.5

    # Every published tariff entry has valid positive kWh price and official https source.
    with_tariffs = [u for u in utilities if u.get("tariffs")]
    assert len(with_tariffs) >= 35
    for u in with_tariffs:
        for t in u["tariffs"]:
            assert t["price_dkk_per_kwh"] > 0, u["id"]
            assert str(t.get("source", "")).startswith("https://"), u["id"]


def test_bundled_utilities_json_has_albertslund_confirmed_and_tariffs() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    albertslund = by_id["albertslund-forsyning"]
    assert albertslund["status"] == "confirmed"
    assert albertslund["tier"] == "confirmed"

    t26 = resolve_tariff(
        _entry(data={"utility_id": "albertslund-forsyning"}),
        today=date(2026, 11, 26),
        utilities=utilities,
    )
    assert t26.price_dkk_per_kwh == 0.84048
    assert t26.motivation_pct_per_k == 1.0
    assert t26.bonus_temp == 35.0
    assert t26.penalty_temp == 40.0

    t27 = resolve_tariff(
        _entry(data={"utility_id": "albertslund-forsyning"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert t27.price_dkk_per_kwh == 0.79863


def test_bundled_utilities_json_has_kalundborg_confirmed_and_tariff() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    kalundborg = by_id["kalundborg-forsyning"]
    assert kalundborg["status"] == "confirmed"
    assert kalundborg["tier"] == "confirmed"

    t26 = resolve_tariff(
        _entry(data={"utility_id": "kalundborg-forsyning"}),
        today=date(2026, 11, 26),
        utilities=utilities,
    )
    assert t26.price_dkk_per_kwh == 0.80625
    assert t26.price_dkk_per_m3 == 0.625
    assert t26.fixed_fee_dkk_per_m2_year == 45.625
    assert t26.motivation_dkk_per_kwh_per_k == 0.00375
    assert t26.bonus_temp == 45.0
    assert t26.penalty_temp == 45.0

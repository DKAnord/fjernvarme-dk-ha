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


def test_bundled_utilities_json_has_kongerslev_2026_2027_tariff_and_custom_matching() -> None:
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    kong = by_id["kongerslev-fjernvarme"]
    assert kong["status"] == "confirmed"
    assert kong["tier"] == "confirmed"
    assert kong["eforsyning_supplier_id"] == "4A530E73-227F-4ACB-9D9B-A84905470921"
    assert kong["portal_url"] == "https://eforsyning.dk/kongerslev/"

    for year in (2026, 2027):
        t = published_tariff("kongerslev-fjernvarme", year, utilities)
        assert t is not None
        assert t["price_dkk_per_kwh"] == 0.6875
        assert t["motivation_pct_per_k"] == 3.0
        assert t["bonus_temp"] == 30.0
        assert t["penalty_temp"] == 37.0
        assert t["source"].startswith("https://kongerslevfjernvarme.dk/")

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "4a530e73-227f-4acb-9d9b-a84905470921",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "kongerslev-fjernvarme"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/kongerslev",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "kongerslev-fjernvarme"

    resolved = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://eforsyning.dk/kongerslev/",
            },
        ),
        today=date(2026, 11, 26),
        utilities=utilities,
    )
    assert resolved.utility_id == "kongerslev-fjernvarme"
    assert resolved.price_dkk_per_kwh == 0.6875
    assert resolved.motivation_pct_per_k == 3.0
    assert resolved.motivation_dkk_per_kwh_per_k == round(0.6875 * 0.03, 6)
    assert resolved.bonus_temp == 30.0
    assert resolved.penalty_temp == 37.0


def test_bundled_utilities_json_has_energi_ikast_2026_2027_tariffs_and_dynamic_curve() -> None:
    from kmd_easy_energy.const import CONF_FIXED_FEE_DKK_PER_YEAR, CONF_HEATED_AREA_M2
    from kmd_easy_energy.insights import estimate_variable_costs
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    ikast = by_id["energi-ikast"]
    assert ikast["status"] == "confirmed"
    assert ikast["tier"] == "confirmed"
    assert ikast["backend"] == "kmd"

    t26 = resolve_tariff(
        _entry(data={"utility_id": "energi-ikast"}),
        today=date(2026, 6, 1),
        utilities=utilities,
    )
    assert t26.price_dkk_per_kwh == 0.59625
    assert t26.fixed_fee_dkk_per_m2_year == 25.0
    assert t26.motivation_dkk_per_kwh_per_k == 0.00375
    assert t26.motivation_max_pct == 10.0
    assert t26.motivation_bonus is False
    assert t26.bonus_temp == 0.0
    assert t26.penalty_temp == 37.0
    assert t26.expected_return_by_forward_temp == [[50.0, 42.0], [70.0, 32.0]]
    assert t26.annual_fixed_fee_dkk == 0.0

    t27 = resolve_tariff(
        _entry(data={"utility_id": "energi-ikast"}),
        today=date(2027, 6, 1),
        utilities=utilities,
    )
    assert t27.price_dkk_per_kwh == 0.57375
    assert t27.fixed_fee_dkk_per_m2_year == 25.0
    assert t27.motivation_dkk_per_kwh_per_k == 0.00375
    assert t27.motivation_max_pct == 10.0
    assert t27.motivation_bonus is False
    assert t27.expected_return_by_forward_temp == [[50.0, 42.0], [70.0, 32.0]]

    # Dynamic supply-temp curve interpolation and clamping
    curve = t26.expected_return_by_forward_temp
    assert expected_return_from_forward_temp(45.0, curve) == 42.0
    assert expected_return_from_forward_temp(50.0, curve) == 42.0
    assert expected_return_from_forward_temp(60.0, curve) == 37.0
    assert expected_return_from_forward_temp(64.0, curve) == 35.0
    assert expected_return_from_forward_temp(70.0, curve) == 32.0
    assert expected_return_from_forward_temp(80.0, curve) == 32.0

    # Penalty-only + 10% max cap via estimate_variable_costs
    below_target = estimate_variable_costs(
        price_dkk_per_kwh=t26.price_dkk_per_kwh,
        bonus_temp=t26.bonus_temp,
        penalty_temp=t26.penalty_temp,
        motivation_rate=t26.motivation_dkk_per_kwh_per_k,
        current_return_temp=33.0,
        daily={"days": {"1": 50.0}, "latest_complete": True, "month": "Jun"},
        monthly_cur_year={"Jun": 50.0},
        return_temp_monthly={"Jun": 33.0},
        today=date(2026, 6, 15),
        max_pct=t26.motivation_max_pct,
        allow_bonus=t26.motivation_bonus,
        annual_fixed_fee_dkk=t26.annual_fixed_fee_dkk,
    )
    assert below_target["adjustment_pct"] == 0.0
    assert below_target["excludes_fixed_fees"] is True

    moderate_penalty = estimate_variable_costs(
        price_dkk_per_kwh=t26.price_dkk_per_kwh,
        bonus_temp=t26.bonus_temp,
        penalty_temp=t26.penalty_temp,
        motivation_rate=t26.motivation_dkk_per_kwh_per_k,
        current_return_temp=41.0,  # +4 °C * 0.00375 = +0.015 kr./kWh
        daily={"days": {"1": 50.0}, "latest_complete": True, "month": "Jun"},
        monthly_cur_year={"Jun": 50.0},
        return_temp_monthly={"Jun": 41.0},
        today=date(2026, 6, 15),
        max_pct=t26.motivation_max_pct,
        allow_bonus=t26.motivation_bonus,
    )
    assert moderate_penalty["effective_price_dkk_per_kwh"] == round(0.59625 + 4 * 0.00375, 4)
    assert moderate_penalty["adjustment_pct"] > 0.0

    capped_penalty = estimate_variable_costs(
        price_dkk_per_kwh=t26.price_dkk_per_kwh,
        bonus_temp=t26.bonus_temp,
        penalty_temp=t26.penalty_temp,
        motivation_rate=t26.motivation_dkk_per_kwh_per_k,
        current_return_temp=65.0,  # +28 °C would exceed 10 % cap
        daily={"days": {"1": 50.0}, "latest_complete": True, "month": "Jun"},
        monthly_cur_year={"Jun": 50.0},
        return_temp_monthly={"Jun": 65.0},
        today=date(2026, 6, 15),
        max_pct=t26.motivation_max_pct,
        allow_bonus=t26.motivation_bonus,
    )
    assert capped_penalty["adjustment_pct"] == 10.0

    # Opt-in heated area + meter fee resolution
    with_area = resolve_tariff(
        _entry(
            options={
                CONF_HEATED_AREA_M2: 140.0,
                CONF_FIXED_FEE_DKK_PER_YEAR: 875.0,
            },
            data={"utility_id": "energi-ikast"},
        ),
        today=date(2026, 6, 1),
        utilities=utilities,
    )
    assert with_area.annual_fixed_fee_dkk == 4375.0
    with_area_est = estimate_variable_costs(
        price_dkk_per_kwh=with_area.price_dkk_per_kwh,
        bonus_temp=with_area.bonus_temp,
        penalty_temp=with_area.penalty_temp,
        motivation_rate=with_area.motivation_dkk_per_kwh_per_k,
        current_return_temp=33.0,
        daily={"days": {"1": 50.0}, "latest_complete": True, "month": "Jun"},
        monthly_cur_year={"Jun": 50.0},
        return_temp_monthly={"Jun": 33.0},
        today=date(2026, 6, 15),
        max_pct=with_area.motivation_max_pct,
        allow_bonus=with_area.motivation_bonus,
        annual_fixed_fee_dkk=with_area.annual_fixed_fee_dkk,
    )
    assert with_area_est["excludes_fixed_fees"] is False
    assert with_area_est["annual_fixed_fee_dkk"] == 4375.0


def test_bundled_utilities_json_all_69_have_tariffs_and_spot_checks() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    assert len(utilities) == 70
    with_tariffs = [u for u in utilities if u.get("tariffs")]
    assert len(with_tariffs) == len(utilities) == 70
    assert len({u["id"] for u in utilities}) == 70

    backends = {}
    for u in utilities:
        b = u.get("backend")
        backends[b] = backends.get(b, 0) + 1
        for t in u["tariffs"]:
            assert t["price_dkk_per_kwh"] > 0, u["id"]
            assert str(t.get("source", "")).startswith("https://"), u["id"]
    assert backends == {"kmd": 17, "eforsyning": 49, "wattson": 4}

    by_id = {u["id"]: u for u in utilities}
    assert "hoje-taastrup-fjernvarme" not in by_id
    assert by_id["envafors"]["portal_url"] == "https://www.envafors.dk/slagelse/selvbetjening/min-side"

    # nykobing-sj migrated from kmd candidate to verified eforsyning
    ny = by_id["nykobing-sj"]
    assert ny["backend"] == "eforsyning"
    assert ny["portal_url"] == "https://eforsyning.dk/nsfv/"
    assert ny["eforsyning_supplier_id"] == "17086977-7E29-4199-917D-1A76641671BC"

    enva = resolve_tariff(
        _entry(data={"utility_id": "envafors"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert enva.price_dkk_per_kwh == 0.67125
    assert enva.price_dkk_per_m3 == 4.0
    assert enva.fixed_fee_dkk_per_m2_year == 27.13
    assert enva.suggested_fixed_fee_dkk_per_year == 828.75

    sonfor_26 = resolve_tariff(
        _entry(data={"utility_id": "sonfor-varme"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert sonfor_26.price_dkk_per_kwh == 0.845
    assert sonfor_26.fixed_fee_dkk_per_m2_year == 55.0

    sonfor_27 = resolve_tariff(
        _entry(data={"utility_id": "sonfor-varme"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert sonfor_27.price_dkk_per_kwh == 0.8875
    assert sonfor_27.fixed_fee_dkk_per_m2_year == 56.38

    koge_26 = resolve_tariff(
        _entry(data={"utility_id": "koge-fjernvarme"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert koge_26.price_dkk_per_kwh == 0.87417
    assert koge_26.fixed_fee_dkk_per_m2_year == 37.83

    koge_27 = resolve_tariff(
        _entry(data={"utility_id": "koge-fjernvarme"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert koge_27.price_dkk_per_kwh == 0.95841
    assert koge_27.fixed_fee_dkk_per_m2_year == 40.45

    # 4 new 2027 additions (+ soroe 2026 fixed m2)
    beof_27 = resolve_tariff(
        _entry(data={"utility_id": "beof"}), today=date(2027, 2, 1), utilities=utilities
    )
    assert beof_27.price_dkk_per_kwh == 0.7421
    assert beof_27.fixed_fee_dkk_per_m2_year == 52.3
    assert beof_27.suggested_fixed_fee_dkk_per_year == 2897.0

    soroe_26 = resolve_tariff(
        _entry(data={"utility_id": "soroe-fjernvarme"}), today=date(2026, 11, 27), utilities=utilities
    )
    assert soroe_26.fixed_fee_dkk_per_m2_year == 35.96
    soroe_27 = resolve_tariff(
        _entry(data={"utility_id": "soroe-fjernvarme"}), today=date(2027, 2, 1), utilities=utilities
    )
    assert soroe_27.price_dkk_per_kwh == 0.94875
    assert soroe_27.fixed_fee_dkk_per_m2_year == 46.82

    frh_27 = resolve_tariff(
        _entry(data={"utility_id": "frederikshavn-forsyning"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert frh_27.price_dkk_per_kwh == 0.9625

    hadsund_27 = resolve_tariff(
        _entry(data={"utility_id": "hadsund-fjernvarme"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert hadsund_27.price_dkk_per_kwh == 0.69

    # Spot-check all 22 newly added utilities
    expected_new_2026 = {
        "frederiksberg-forsyning": 0.62426,
        "silkeborg-forsyning": 0.855,
        "bronderslev-forsyning": 0.75825,
        "lolland-forsyning": 0.445,
        "halsnaes-forsyning": 0.83,
        "kerteminde-forsyning": 0.642,
        "viborg-varme": 0.79,
        "naestved-fjernvarme": 0.69938,
        "svendborg-fjernvarme": 0.735,
        "gentofte-fjernvarme": 0.33436,
        "gladsaxe-fjernvarme": 0.37745,
        "norfors-fjernvarme": 0.93758,
        "greve-fjernvarme": 0.3375,
        "rodovre-fjernvarme": 0.78,
        "brondby-fjernvarme": 0.488,
        "taarnby-forsyning": 0.47813,
        "skive-fjernvarme": 0.785,
        "haderslev-fjernvarme": 0.66575,
        "aabenraa-fjernvarme": 0.511,
        "skanderborg-horning-fjernvarme": 0.5825,
        "vordingborg-fjernvarme": 0.96,
        "hobro-varmevaerk": 0.79144,
    }
    for uid, exp_price in expected_new_2026.items():
        res = resolve_tariff(
            _entry(data={"utility_id": uid}),
            today=date(2026, 11, 27),
            utilities=utilities,
        )
        assert res.price_dkk_per_kwh == exp_price, uid

    # Specific rules on new utilities
    frb = resolve_tariff(
        _entry(data={"utility_id": "frederiksberg-forsyning"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert frb.motivation_bonus is False
    assert frb.penalty_temp == 50.0

    hnf = resolve_tariff(
        _entry(data={"utility_id": "halsnaes-forsyning"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert hnf.motivation_bonus is False
    assert hnf.penalty_temp == 40.0
    assert hnf.expected_return_by_forward_temp and [65.0, 40.0] in hnf.expected_return_by_forward_temp

    silk_jan27 = resolve_tariff(
        _entry(data={"utility_id": "silkeborg-forsyning"}),
        today=date(2027, 1, 15),
        utilities=utilities,
    )
    assert silk_jan27.price_dkk_per_kwh == 0.855
    silk_feb27 = resolve_tariff(
        _entry(data={"utility_id": "silkeborg-forsyning"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert silk_feb27.price_dkk_per_kwh == 1.04

    ny_feb27 = resolve_tariff(
        _entry(data={"utility_id": "nykobing-sj"}),
        today=date(2027, 2, 15),
        utilities=utilities,
    )
    assert ny_feb27.price_dkk_per_kwh == 0.56
    ny_mar27 = resolve_tariff(
        _entry(data={"utility_id": "nykobing-sj"}),
        today=date(2027, 3, 1),
        utilities=utilities,
    )
    assert ny_mar27.price_dkk_per_kwh == 0.94

    vib_27 = resolve_tariff(
        _entry(data={"utility_id": "viborg-varme"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert vib_27.price_dkk_per_kwh == 0.809
    assert vib_27.motivation_max_pct == 25.0


def test_asymmetric_motivation_rates_and_suggested_fixed_fee_year() -> None:
    from kmd_easy_energy.const import (
        CONF_FIXED_FEE_DKK_PER_YEAR,
        CONF_MOTIVATION_DKK_PER_KWH_PER_K,
        CONF_MOTIVATION_PCT_PER_K,
        CONF_PRICE_DKK_PER_KWH,
    )
    from kmd_easy_energy.insights import estimate_variable_costs, motivation_dkk_per_kwh
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()

    # 1. Fixed DKK/kWh/K asymmetry + 2026->2027 transition (synthetic utility)
    asym_utilities = [
        {
            "id": "synthetic-asym-varme",
            "tariffs": [
                {
                    "year": 2026,
                    "effective_from": "2026-01-01",
                    "price_dkk_per_kwh": 0.6925,
                    "fixed_fee_dkk_per_m2_year": 36.52,
                    "motivation_dkk_per_kwh_per_k": 0.01076,
                    "motivation_bonus_dkk_per_kwh_per_k": 0.00538,
                    "bonus_temp": 41.0,
                    "penalty_temp": 41.0,
                    "fixed_fee_dkk_per_year": 1567.5,
                },
                {
                    "year": 2027,
                    "effective_from": "2027-01-01",
                    "price_dkk_per_kwh": 0.71625,
                    "fixed_fee_dkk_per_m2_year": 37.71,
                    "motivation_dkk_per_kwh_per_k": 0.01113,
                    "motivation_bonus": False,
                    "bonus_temp": 0.0,
                    "penalty_temp": 41.0,
                    "fixed_fee_dkk_per_year": 1618.75,
                },
            ],
        }
    ]
    asym_26 = resolve_tariff(
        _entry(data={"utility_id": "synthetic-asym-varme"}),
        today=date(2026, 11, 27),
        utilities=asym_utilities,
    )
    assert asym_26.price_dkk_per_kwh == 0.6925
    assert asym_26.fixed_fee_dkk_per_m2_year == 36.52
    assert asym_26.motivation_dkk_per_kwh_per_k == 0.01076
    assert asym_26.motivation_bonus_dkk_per_kwh_per_k == 0.00538
    assert asym_26.motivation_penalty_dkk_per_kwh_per_k == 0.01076
    assert asym_26.bonus_temp == 41.0
    assert asym_26.penalty_temp == 41.0
    assert asym_26.motivation_bonus is True
    assert asym_26.suggested_fixed_fee_dkk_per_year == 1567.5
    assert asym_26.fixed_fee_dkk_per_year is None
    assert asym_26.annual_fixed_fee_dkk == 0.0

    asym_27 = resolve_tariff(
        _entry(data={"utility_id": "synthetic-asym-varme"}),
        today=date(2027, 2, 1),
        utilities=asym_utilities,
    )
    assert asym_27.price_dkk_per_kwh == 0.71625
    assert asym_27.fixed_fee_dkk_per_m2_year == 37.71
    assert asym_27.motivation_dkk_per_kwh_per_k == 0.01113
    assert asym_27.motivation_bonus is False
    assert asym_27.bonus_temp == 0.0
    assert asym_27.penalty_temp == 41.0

    bonus_adj = motivation_dkk_per_kwh(
        39.0,
        asym_26.bonus_temp,
        asym_26.penalty_temp,
        asym_26.motivation_dkk_per_kwh_per_k,
        bonus_rate=asym_26.motivation_bonus_dkk_per_kwh_per_k,
        penalty_rate=asym_26.motivation_penalty_dkk_per_kwh_per_k,
    )
    penalty_adj = motivation_dkk_per_kwh(
        43.0,
        asym_26.bonus_temp,
        asym_26.penalty_temp,
        asym_26.motivation_dkk_per_kwh_per_k,
        bonus_rate=asym_26.motivation_bonus_dkk_per_kwh_per_k,
        penalty_rate=asym_26.motivation_penalty_dkk_per_kwh_per_k,
    )
    assert bonus_adj == -0.01076
    assert penalty_adj == 0.02152

    # User motivation override forces symmetric rates and clears asymmetric split
    asym_ovr = resolve_tariff(
        _entry(
            data={"utility_id": "synthetic-asym-varme"},
            options={
                CONF_MOTIVATION_DKK_PER_KWH_PER_K: 0.02,
                CONF_FIXED_FEE_DKK_PER_YEAR: 1567.5,
            },
        ),
        today=date(2026, 11, 27),
        utilities=asym_utilities,
    )
    assert asym_ovr.motivation_bonus_dkk_per_kwh_per_k == 0.02
    assert asym_ovr.motivation_penalty_dkk_per_kwh_per_k == 0.02
    assert asym_ovr.annual_fixed_fee_dkk == 1567.5

    # 2. Percentage asymmetry + price scaling: Sønderborg (-1% bonus / +0.5% penalty)
    sond_scaled = resolve_tariff(
        _entry(
            data={"utility_id": "sonderborg-varme"},
            options={CONF_PRICE_DKK_PER_KWH: 1.0},
        ),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert sond_scaled.motivation_bonus_pct_per_k == 1.0
    assert sond_scaled.motivation_penalty_pct_per_k == 0.5
    assert sond_scaled.motivation_bonus_dkk_per_kwh_per_k == 0.01
    assert sond_scaled.motivation_penalty_dkk_per_kwh_per_k == 0.005

    sond_pct_ovr = resolve_tariff(
        _entry(
            data={"utility_id": "sonderborg-varme"},
            options={CONF_PRICE_DKK_PER_KWH: 1.0, CONF_MOTIVATION_PCT_PER_K: 2.0},
        ),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert sond_pct_ovr.motivation_bonus_pct_per_k == 2.0
    assert sond_pct_ovr.motivation_penalty_pct_per_k == 2.0
    assert sond_pct_ovr.motivation_bonus_dkk_per_kwh_per_k == 0.02
    assert sond_pct_ovr.motivation_penalty_dkk_per_kwh_per_k == 0.02

    # 3. Hvide Sande (-3% bonus / +12% penalty) in estimate_variable_costs
    hs = resolve_tariff(
        _entry(data={"utility_id": "hvide-sande-fjernvarme"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert hs.motivation_bonus_pct_per_k == 3.0
    assert hs.motivation_penalty_pct_per_k == 12.0
    est = estimate_variable_costs(
        price_dkk_per_kwh=hs.price_dkk_per_kwh,
        bonus_temp=35.0,
        penalty_temp=40.0,
        motivation_rate=hs.motivation_dkk_per_kwh_per_k,
        current_return_temp=42.0,
        daily=None,
        monthly_cur_year={"Jan": 1000.0},
        return_temp_monthly={"Jan": 42.0},
        today=date(2026, 11, 27),
        bonus_rate=hs.motivation_bonus_dkk_per_kwh_per_k,
        penalty_rate=hs.motivation_penalty_dkk_per_kwh_per_k,
    )
    # Base 0.0125 + 2 °C * (12% * 0.0125 = 0.0015) = 0.0155 DKK/kWh -> 1000 * 0.0155 = 16 kr
    assert est["effective_price_dkk_per_kwh"] == 0.0155
    assert est["monthly_dkk"]["Jan"] == 16


def test_bundled_utilities_json_has_vestforsyning_confirmed_and_tariffs() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    vest = by_id["vestforsyning"]
    assert vest["status"] == "confirmed"
    assert vest["tier"] == "confirmed"

    t26 = resolve_tariff(
        _entry(data={"utility_id": "vestforsyning"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert t26.price_dkk_per_kwh == 0.67375
    assert t26.fixed_fee_dkk_per_m2_year == 20.4
    assert t26.motivation_dkk_per_kwh_per_k == 0.00375

    t27 = resolve_tariff(
        _entry(data={"utility_id": "vestforsyning"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert t27.price_dkk_per_kwh == 0.70125
    assert t27.fixed_fee_dkk_per_m2_year == 21.2125
    assert t27.motivation_dkk_per_kwh_per_k == 0.00375


def test_bundled_utilities_json_has_grenaa_2026_tariff_and_custom_matching() -> None:
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    grenaa = by_id["grenaa-varmevaerk"]
    assert grenaa["status"] == "confirmed"
    assert grenaa["tier"] == "confirmed"
    assert grenaa["eforsyning_supplier_id"] == "BE112409-C45D-4E63-BFF6-1C4E8F9ED990"
    assert grenaa["portal_url"] == "https://eforsyning.dk/grenaa-varmevaerk/"

    t = published_tariff("grenaa-varmevaerk", 2026, utilities)
    assert t is not None
    assert t["price_dkk_per_kwh"] == 0.39
    assert t["fixed_fee_dkk_per_m2_year"] == 28.25
    assert t["fixed_fee_dkk_per_year"] == 975.0
    assert t["motivation_pct_per_k"] == 1.0
    assert t["bonus_temp"] == 32.0
    assert t["penalty_temp"] == 35.0
    assert t["source"].startswith("https://grenaa-varmevaerk.dk/")

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "be112409-c45d-4e63-bff6-1c4e8f9ed990",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "grenaa-varmevaerk"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/grenaa-varmevaerk",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "grenaa-varmevaerk"

    resolved = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://eforsyning.dk/grenaa-varmevaerk/",
            },
        ),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert resolved.utility_id == "grenaa-varmevaerk"
    assert resolved.price_dkk_per_kwh == 0.39
    assert resolved.fixed_fee_dkk_per_m2_year == 28.25
    assert resolved.suggested_fixed_fee_dkk_per_year == 975.0
    assert resolved.motivation_pct_per_k == 1.0
    assert resolved.motivation_dkk_per_kwh_per_k == round(0.39 * 0.01, 6)
    assert resolved.bonus_temp == 32.0
    assert resolved.penalty_temp == 35.0


def test_bundled_utilities_json_has_vinderup_2026_2027_tariffs_and_custom_matching() -> None:
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    vinderup = by_id["vinderup-varmevaerk"]
    assert vinderup["status"] == "confirmed"
    assert vinderup["tier"] == "confirmed"
    assert vinderup["eforsyning_supplier_id"] == "C0584E30-4F38-4774-B32E-7F6E6AFCCA35"
    assert vinderup["portal_url"] == "https://eforsyning.dk/vinderupvarme/"

    t26 = published_tariff("vinderup-varmevaerk", 2026, utilities)
    assert t26 is not None
    assert t26["price_dkk_per_kwh"] == 0.5
    assert t26["fixed_fee_dkk_per_m2_year"] == 22.38
    assert t26["fixed_fee_dkk_per_year"] == 750.0
    assert t26["motivation_dkk_per_kwh_per_k"] == 0.00625
    assert t26["bonus_temp"] == 30.0
    assert t26["penalty_temp"] == 35.0
    assert t26["source"].startswith("https://vinderupvarme.dk/")

    t27 = published_tariff("vinderup-varmevaerk", 2027, utilities)
    assert t27 is not None
    assert t27["price_dkk_per_kwh"] == 0.575
    assert t27["fixed_fee_dkk_per_m2_year"] == 22.38
    assert t27["fixed_fee_dkk_per_year"] == 750.0
    assert t27["motivation_dkk_per_kwh_per_k"] == 0.00625
    assert t27["bonus_temp"] == 30.0
    assert t27["penalty_temp"] == 35.0
    assert t27["source"].startswith("https://vinderupvarme.dk/")

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "c0584e30-4f38-4774-b32e-7f6e6afcca35",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "vinderup-varmevaerk"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/vinderupvarme",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "vinderup-varmevaerk"

    r26 = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://eforsyning.dk/vinderupvarme/",
            },
        ),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert r26.utility_id == "vinderup-varmevaerk"
    assert r26.price_dkk_per_kwh == 0.5
    assert r26.fixed_fee_dkk_per_m2_year == 22.38
    assert r26.suggested_fixed_fee_dkk_per_year == 750.0
    assert r26.motivation_dkk_per_kwh_per_k == 0.00625
    assert r26.bonus_temp == 30.0
    assert r26.penalty_temp == 35.0

    r27 = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://eforsyning.dk/vinderupvarme/",
            },
        ),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert r27.utility_id == "vinderup-varmevaerk"
    assert r27.price_dkk_per_kwh == 0.575
    assert r27.fixed_fee_dkk_per_m2_year == 22.38
    assert r27.suggested_fixed_fee_dkk_per_year == 750.0
    assert r27.motivation_dkk_per_kwh_per_k == 0.00625
    assert r27.bonus_temp == 30.0
    assert r27.penalty_temp == 35.0


def test_bundled_utilities_json_has_marstal_2026_tariff_and_custom_matching() -> None:
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    marstal = by_id["marstal-fjernvarme"]
    assert marstal["status"] == "confirmed"
    assert marstal["tier"] == "confirmed"
    assert marstal["eforsyning_supplier_id"] == "6BC25F8C-370A-40AB-9971-603C31AEDCA8"
    assert marstal["portal_url"] == "https://www.solarmarstal.dk/eforsyning/"

    t26 = published_tariff("marstal-fjernvarme", 2026, utilities)
    assert t26 is not None
    assert t26["price_dkk_per_kwh"] == 0.88
    assert t26["fixed_fee_dkk_per_year"] == 500.0
    assert t26.get("fixed_fee_dkk_per_m2_year") is None
    assert t26["source"].startswith("https://solarmarstal.dk/")

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "6bc25f8c-370a-40ab-9971-603c31aedca8",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "marstal-fjernvarme"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://www.solarmarstal.dk/eforsyning",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "marstal-fjernvarme"

    resolved = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://www.solarmarstal.dk/eforsyning/",
            },
        ),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert resolved.utility_id == "marstal-fjernvarme"
    assert resolved.price_dkk_per_kwh == 0.88
    assert resolved.fixed_fee_dkk_per_m2_year is None
    assert resolved.suggested_fixed_fee_dkk_per_year == 500.0
    assert resolved.motivation_dkk_per_kwh_per_k is None


def test_bundled_utilities_json_has_silkeborg_confirmed_and_spjald_2026_2027_tariffs() -> None:
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}

    silkeborg = by_id["silkeborg-forsyning"]
    assert silkeborg["status"] == "confirmed"
    assert silkeborg["tier"] == "confirmed"

    spjald = by_id["spjald-fjernvarme"]
    assert spjald["status"] == "confirmed"
    assert spjald["tier"] == "confirmed"
    assert spjald["eforsyning_supplier_id"] == "B9B79876-4611-4549-933D-93A321AE1AEC"
    assert spjald["portal_url"] == "https://eforsyning.dk/spjaldvarme/"

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "b9b79876-4611-4549-933d-93a321ae1aec",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "spjald-fjernvarme"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/spjaldvarme",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "spjald-fjernvarme"

    r_nov = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://eforsyning.dk/spjaldvarme/",
            },
        ),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert r_nov.utility_id == "spjald-fjernvarme"
    assert r_nov.price_dkk_per_kwh == 0.9125
    assert r_nov.fixed_fee_dkk_per_m2_year == 37.5
    assert r_nov.suggested_fixed_fee_dkk_per_year == 1875.0
    assert r_nov.motivation_dkk_per_kwh_per_k is None

    r_dec = resolve_tariff(
        _entry(data={"utility_id": "spjald-fjernvarme"}),
        today=date(2026, 12, 1),
        utilities=utilities,
    )
    assert r_dec.price_dkk_per_kwh == 1.0
    assert r_dec.fixed_fee_dkk_per_m2_year == 37.5
    assert r_dec.suggested_fixed_fee_dkk_per_year == 1875.0

    r_27 = resolve_tariff(
        _entry(data={"utility_id": "spjald-fjernvarme"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert r_27.price_dkk_per_kwh == 1.0
    assert r_27.fixed_fee_dkk_per_m2_year == 37.5
    assert r_27.suggested_fixed_fee_dkk_per_year == 1875.0


def test_odder_forsyning_confirmed_2026_2027_and_dynamic_curve() -> None:
    from kmd_easy_energy.tariff import (
        expected_return_from_forward_temp,
        load_utilities,
        match_utility_for_entry,
    )

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    odder = by_id["odder-forsyning"]
    assert odder["status"] == "confirmed"
    assert odder["tier"] == "confirmed"
    assert odder["eforsyning_supplier_id"] == "ACD7B9D3-E7FA-41DF-A4C1-3E459AD74660"
    assert odder["portal_url"] == "https://eforsyning.dk/odderforsyningsselskab-varme/"

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "acd7b9d3-e7fa-41df-a4c1-3e459ad74660",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "odder-forsyning"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/odderforsyningsselskab-varme",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "odder-forsyning"

    r_26 = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://eforsyning.dk/odderforsyningsselskab-varme/",
            },
        ),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert r_26.utility_id == "odder-forsyning"
    assert r_26.price_dkk_per_kwh == 0.8625
    assert r_26.fixed_fee_dkk_per_m2_year == 22.5
    assert r_26.suggested_fixed_fee_dkk_per_year == 1250.0
    assert r_26.motivation_pct_per_k == 3.0
    assert r_26.motivation_bonus is False
    assert r_26.bonus_temp == 0.0
    assert r_26.penalty_temp == 35.0
    assert r_26.motivation_dkk_per_kwh_per_k == round(0.8625 * 0.03, 6)

    curve = r_26.expected_return_by_forward_temp
    assert curve is not None
    assert expected_return_from_forward_temp(62.0, curve) == 35.0
    assert expected_return_from_forward_temp(58.0, curve) == 36.0
    assert expected_return_from_forward_temp(50.0, curve) == 40.0

    r_27 = resolve_tariff(
        _entry(data={"utility_id": "odder-forsyning"}),
        today=date(2027, 1, 15),
        utilities=utilities,
    )
    assert r_27.price_dkk_per_kwh == 0.9225
    assert r_27.fixed_fee_dkk_per_m2_year == 22.5
    assert r_27.suggested_fixed_fee_dkk_per_year == 1250.0
    assert r_27.motivation_pct_per_k == 3.0
    assert r_27.motivation_bonus is False


def test_hammel_fjernvarme_confirmed_2026_and_custom_matching() -> None:
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    hammel = by_id["hammel-fjernvarme"]
    assert hammel["status"] == "confirmed"
    assert hammel["tier"] == "confirmed"
    assert hammel["eforsyning_supplier_id"] == "F97D7E2D-EB87-4122-A01F-44244527317A"
    assert hammel["portal_url"] == "https://eforsyning.dk/hammelfjernvarme/"

    t26 = published_tariff("hammel-fjernvarme", 2026, utilities)
    assert t26 is not None
    assert t26["price_dkk_per_kwh"] == 0.59375
    assert t26["fixed_fee_dkk_per_m2_year"] == 28.75
    assert t26["fixed_fee_dkk_per_year"] == 1375.0
    assert t26["source"].startswith("https://hammelfjernvarme.dk/")

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "f97d7e2d-eb87-4122-a01f-44244527317a",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "hammel-fjernvarme"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/hammelfjernvarme",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "hammel-fjernvarme"

    resolved = resolve_tariff(
        _entry(
            data={
                "utility_id": "eforsyning-custom",
                "portal_url": "https://eforsyning.dk/hammelfjernvarme/",
            },
        ),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert resolved.utility_id == "hammel-fjernvarme"
    assert resolved.price_dkk_per_kwh == 0.59375
    assert resolved.fixed_fee_dkk_per_m2_year == 28.75
    assert resolved.suggested_fixed_fee_dkk_per_year == 1375.0
    assert resolved.motivation_dkk_per_kwh_per_k is None


def test_bronderslev_forsyning_confirmed_2026_tariff() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    bronderslev = by_id["bronderslev-forsyning"]
    assert bronderslev["status"] == "confirmed"
    assert bronderslev["tier"] == "confirmed"

    resolved = resolve_tariff(
        _entry(data={"utility_id": "bronderslev-forsyning"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert resolved.utility_id == "bronderslev-forsyning"
    assert resolved.price_dkk_per_kwh == 0.75825
    assert resolved.fixed_fee_dkk_per_m2_year == 18.35
    assert resolved.suggested_fixed_fee_dkk_per_year == 918.75
    assert resolved.motivation_pct_per_k == 1.0
    assert resolved.motivation_bonus is False
    assert resolved.bonus_temp == 0.0
    assert resolved.penalty_temp == 30.0
    assert resolved.motivation_dkk_per_kwh_per_k == round(0.75825 * 0.01, 6)


def test_greve_fjernvarme_confirmed_2026_and_2027_tariffs() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    greve = by_id["greve-fjernvarme"]
    assert greve["status"] == "confirmed"
    assert greve["tier"] == "confirmed"

    resolved_2026 = resolve_tariff(
        _entry(data={"utility_id": "greve-fjernvarme"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert resolved_2026.utility_id == "greve-fjernvarme"
    assert resolved_2026.price_dkk_per_kwh == 0.3375
    assert resolved_2026.price_dkk_per_m3 == 6.48
    assert resolved_2026.fixed_fee_dkk_per_m2_year == 35.39
    assert resolved_2026.suggested_fixed_fee_dkk_per_year == 375.0

    resolved_2027 = resolve_tariff(
        _entry(data={"utility_id": "greve-fjernvarme"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert resolved_2027.utility_id == "greve-fjernvarme"
    assert resolved_2027.price_dkk_per_kwh == 0.3825
    assert resolved_2027.price_dkk_per_m3 == 6.85
    assert resolved_2027.fixed_fee_dkk_per_m2_year == 35.39
    assert resolved_2027.suggested_fixed_fee_dkk_per_year == 600.0


def test_viborg_varme_and_aalestrup_norager_confirmed_tariffs() -> None:
    from kmd_easy_energy.tariff import load_utilities, match_utility_for_entry

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}

    viborg = by_id["viborg-varme"]
    assert viborg["status"] == "confirmed"
    assert viborg["tier"] == "confirmed"
    assert viborg["eforsyning_supplier_id"] == "074B5C36-0756-4BFF-A6F3-E694532776BA"
    assert viborg["portal_url"] == "https://eforsyning.dk/viborg/"

    v26 = resolve_tariff(
        _entry(data={"utility_id": "viborg-varme"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert v26.utility_id == "viborg-varme"
    assert v26.price_dkk_per_kwh == 0.79
    assert v26.fixed_fee_dkk_per_m2_year == 29.75
    assert v26.suggested_fixed_fee_dkk_per_year == 665.0
    assert v26.motivation_pct_per_k == 1.0
    assert v26.motivation_max_pct == 25.0

    v27 = resolve_tariff(
        _entry(data={"utility_id": "viborg-varme"}),
        today=date(2027, 2, 1),
        utilities=utilities,
    )
    assert v27.utility_id == "viborg-varme"
    assert v27.price_dkk_per_kwh == 0.809
    assert v27.fixed_fee_dkk_per_m2_year == 27.88
    assert v27.suggested_fixed_fee_dkk_per_year == 665.0
    assert v27.motivation_pct_per_k == 1.0
    assert v27.motivation_max_pct == 25.0

    aalestrup = by_id["aalestrup-norager-energi"]
    assert aalestrup["status"] == "confirmed"
    assert aalestrup["tier"] == "confirmed"
    assert aalestrup["eforsyning_supplier_id"] == "5AE1507E-D219-49F4-95FB-C87338FC67A0"
    assert aalestrup["portal_url"] == "https://eforsyning.dk/an-energi-varme/"

    by_supplier = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "eforsyning_supplier_id": "5ae1507e-d219-49f4-95fb-c87338fc67a0",
            "portal_url": "https://eforsyning.dk/",
        },
        utilities,
    )
    assert by_supplier is not None and by_supplier["id"] == "aalestrup-norager-energi"

    by_portal = match_utility_for_entry(
        {
            "utility_id": "eforsyning-custom",
            "portal_url": "https://eforsyning.dk/an-energi-varme",
        },
        utilities,
    )
    assert by_portal is not None and by_portal["id"] == "aalestrup-norager-energi"

    a_70 = resolve_tariff(
        _entry(data={"utility_id": "aalestrup-norager-energi"}),
        today=date(2026, 11, 27),
        utilities=utilities,
        forward_temp=70.0,
    )
    assert a_70.utility_id == "aalestrup-norager-energi"
    assert a_70.price_dkk_per_kwh == 0.4775
    assert a_70.fixed_fee_dkk_per_m2_year == 20.63
    assert a_70.suggested_fixed_fee_dkk_per_year == 725.0
    assert a_70.motivation_pct_per_k == 1.0
    assert a_70.motivation_max_pct == 15.0
    assert a_70.motivation_bonus is True
    assert a_70.bonus_temp == 31.0
    assert a_70.penalty_temp == 31.0

    a_55 = resolve_tariff(
        _entry(data={"utility_id": "aalestrup-norager-energi"}),
        today=date(2026, 11, 27),
        utilities=utilities,
        forward_temp=55.0,
    )
    assert a_55.bonus_temp == 39.0
    assert a_55.penalty_temp == 39.0

    a_82 = resolve_tariff(
        _entry(data={"utility_id": "aalestrup-norager-energi"}),
        today=date(2026, 11, 27),
        utilities=utilities,
        forward_temp=82.0,
    )
    assert a_82.bonus_temp == 25.0
    assert a_82.penalty_temp == 25.0


def test_aabenraa_fjernvarme_confirmed_2026_and_2027_tariffs() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    aabenraa = by_id["aabenraa-fjernvarme"]
    assert aabenraa["status"] == "confirmed"
    assert aabenraa["tier"] == "confirmed"
    assert aabenraa["eforsyning_supplier_id"] == "36793E9C-71E7-4DD5-B386-654FEEEEDB21"
    assert aabenraa["portal_url"] == "https://eforsyning.dk/aabenraa-fjernvarme/"

    for check_date in (date(2026, 11, 27), date(2027, 2, 1)):
        res = resolve_tariff(
            _entry(data={"utility_id": "aabenraa-fjernvarme"}),
            today=check_date,
            utilities=utilities,
        )
        assert res.utility_id == "aabenraa-fjernvarme"
        assert res.price_dkk_per_kwh == 0.511
        assert res.fixed_fee_dkk_per_m2_year == 12.5
        assert res.suggested_fixed_fee_dkk_per_year == 750.0
        assert res.motivation_pct_per_k == 1.0
        assert res.motivation_bonus is False
        assert res.bonus_temp == 0.0
        assert res.penalty_temp == 40.0

    for fwd, expected_ret in ((50.0, 44.0), (60.0, 40.0), (70.0, 37.0), (75.0, 36.0)):
        res = resolve_tariff(
            _entry(data={"utility_id": "aabenraa-fjernvarme"}),
            today=date(2026, 11, 27),
            utilities=utilities,
            forward_temp=fwd,
        )
        assert res.bonus_temp == 0.0
        assert res.penalty_temp == expected_ret


def test_nyborg_forsyning_2026_tariff() -> None:
    from kmd_easy_energy.tariff import load_utilities

    utilities = load_utilities()
    by_id = {u["id"]: u for u in utilities}
    nyborg = by_id["nyborg-forsyning"]
    assert nyborg["backend"] == "kmd"
    assert nyborg["status"] == "pending_test"
    assert nyborg["tier"] == "verified_portal"
    assert nyborg["portal_url"] == "https://minforsyning-2.kmd.dk/?plant=120&utility=0&plus=True"

    resolved = resolve_tariff(
        _entry(data={"utility_id": "nyborg-forsyning"}),
        today=date(2026, 11, 27),
        utilities=utilities,
    )
    assert resolved.utility_id == "nyborg-forsyning"
    assert resolved.price_dkk_per_kwh == 0.75
    assert resolved.fixed_fee_dkk_per_m2_year == 16.0
    assert resolved.suggested_fixed_fee_dkk_per_year == 750.0
    assert resolved.motivation_dkk_per_kwh_per_k is None

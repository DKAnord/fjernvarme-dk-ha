// Node harness: capability-driven rendering + E|Forsyning / Watts On backends (no real HA / network).
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

class FakeShadow {
  constructor() { this.innerHTML = ""; this.els = {}; }
  getElementById(id) {
    if (!this.innerHTML.includes(`id="${id}"`)) return null;
    if (!this.els[id]) this.els[id] = { id, value: "", listeners: {}, addEventListener(ev, fn) { this.listeners[ev] = fn; }, setAttribute() {}, style: {}, classList: { add() {}, remove() {}, toggle() {} } };
    return this.els[id];
  }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
global.HTMLElement = class { attachShadow() { this.shadowRoot = new FakeShadow(); return this.shadowRoot; } };
const defined = {};
global.customElements = { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } };
global.window = global;
global.document = { createElement: () => ({}) };
global.setInterval = () => 0;
global.clearInterval = () => {};
eval(fs.readFileSync(path.join(__dirname, "../../custom_components/kmd_easy_energy/frontend/kmd-easy-energy-card.js"), "utf8"));
const Card = defined["kmd-easy-energy-card"];

function mkHass(attrs, calls) {
  return {
    states: {
      "sensor.kredslob_overview": {
        entity_id: "sensor.kredslob_overview", state: "1234",
        attributes: Object.assign({
          utility_id: "kredslob", entry_id: "e1", portal_url: "https://minvarme.kredslob.dk/",
          initial_setup_complete: true,
          annual: { "2026": 1234 }, monthly: { "2026": { Jan: 100 } }, daily: { days: { "1": 10, "2": 11 }, month: "November 2026", total: 21, gennemsnit: 10.5 },
        }, attrs),
      },
    },
    services: { notify: {} },
    language: "da",
    connection: { subscribeMessage: () => Promise.resolve(() => {}) },
    callService: async (d, s, data) => { calls.push([d, s, data]); },
  };
}


const ALL_KMD = ["billing", "cost", "daily", "forecast", "hourly", "mitid", "monthly", "reminder", "temperatures", "volume"];
const EF_ATTRS = {
  backend: "eforsyning", data_source: "E|Forsyning", utility: "Hjørring Varmeforsyning",
  utility_id: "hjorring-varmeforsyning", portal_url: "https://eforsyning.dk/hjvarme/",
  auto_sync: true, auto_sync_hour: 6, hourly: {}, billing: {}, forecast: {},
  return_temp: { annual: { "2026": 31.2 }, monthly_2026: { Nov: 31.2 } },
  capabilities: ["auto_sync", "cost", "daily", "monthly", "temperatures", "volume"],
};
const render = (attrs, calls) => { const c = new Card(); c.setConfig({}); c.hass = mkHass(attrs, calls); return c; };
const sections = (html) => (html.match(/data-section="([^"]+)"/g) || []).map((m) => m.slice(14, -1));

// 1) KMD with all capabilities: every section present, MitID wording available.
let calls = [];
let card = render({ capabilities: ALL_KMD, backend: "kmd", hourly: { kwh: Array(24).fill(1) } }, calls);
let html = card.shadowRoot.innerHTML;
for (const s of ["monthly", "return-temp", "hourly", "mtd-ytd", "daily", "ins-hourly", "ins-temp"]) {
  assert.ok(sections(html).includes(s), `KMD shows ${s}`);
}
assert.ok(html.includes("Afregning") || html.includes("kr."), "billing tile shown for KMD");
assert.ok(!html.includes('class="src-note"'), "no data-source note for KMD");

// 2) E|Forsyning: no hourly graph/insight, no billing/forecast tiles, note shown, no MitID.
calls = [];
card = render(EF_ATTRS, calls);
html = card.shadowRoot.innerHTML;
const secs = sections(html);
assert.ok(!secs.includes("hourly") && !secs.includes("ins-hourly"), "no hourly sections without hourly data");
assert.ok(secs.includes("daily") && secs.includes("monthly") && secs.includes("return-temp"), "daily/monthly/temp shown");
assert.ok(!html.includes("Saldo"), "no billing tile");
assert.ok(!/budget/.test(html), "no forecast tile");
assert.ok(html.includes("Data fra E|Forsyning"), "data-source note");
assert.ok(html.includes("daglige aflæsninger"), "granularity note");
assert.ok(!/MitID/.test(html), "no MitID UI or wording for E|Forsyning");
assert.ok(html.includes("Hjørring Varmeforsyning"), "utility name from integration");
card.shadowRoot.getElementById("syncBtn").listeners.click();
assert.deepStrictEqual(calls.pop(), ["kmd_easy_energy", "sync", { entry_id: "e1" }], "sync service, not start_mitid_sync");

// 3) No temperatures capability -> no temp KPI, panel or insight.
calls = [];
card = render(Object.assign({}, EF_ATTRS, { capabilities: ["daily", "monthly"] }), calls);
html = card.shadowRoot.innerHTML;
assert.ok(!sections(html).includes("return-temp") && !sections(html).includes("ins-temp"), "temp sections hidden");
assert.ok(!html.includes("Bonus-zone") && !html.includes("Grænser:"), "temp KPI hidden");

// 4) E|Forsyning first-time setup: simple onboarding, no MitID wizard, optional tariff section collapsed.
calls = [];
card = render(Object.assign({}, EF_ATTRS, { initial_setup_complete: false, annual: {}, monthly: {}, daily: {} }), calls);
html = card.shadowRoot.innerHTML;
assert.ok(html.includes('id="efSyncBtn"'), "E|Forsyning onboarding button");
assert.ok(!html.includes('id="mitidUserInput"') && !html.includes("startMitidBtn"), "no MitID wizard");
assert.ok(html.includes('<details class="ob-manual" >') || html.includes('<details class="ob-manual">'), "optional tariff fields collapsed for casual onboarding");
assert.ok(!html.includes('<details class="ob-manual" open>'), "not expanded during initial onboarding");
card.shadowRoot.getElementById("efSyncBtn").listeners.click();
assert.deepStrictEqual(calls.pop()[1], "sync");

// 5) Legacy attributes without capabilities -> everything shown (backwards compatible).
calls = [];
card = render({ hourly: { kwh: Array(24).fill(1) } }, calls);
html = card.shadowRoot.innerHTML;
assert.ok(sections(html).includes("hourly") && html.includes("Saldo"), "legacy: all sections");
card.shadowRoot.getElementById("syncBtn").listeners.click();
assert.strictEqual(calls.pop()[1], "sync");

// 6) MitID wizard utility list only offers KMD utilities.
calls = [];
card = render({ capabilities: ALL_KMD, initial_setup_complete: false, annual: {}, monthly: {}, daily: {} }, calls);
html = card.shadowRoot.innerHTML;
assert.ok(html.includes('id="mitidUserInput"'), "KMD wizard");
assert.ok(!html.includes('value="hjorring-varmeforsyning"'), "E|Forsyning utility not in MitID wizard");
assert.ok(!html.includes('value="soroe-fjernvarme"'), "Sorø E|Forsyning utility not in MitID wizard");

// 7) Watts On (Aalborg): hourly data detected -> hourly sections shown, no MitID,
//    no "daglige aflæsninger", data-source note, sync service.
const W_ATTRS = {
  backend: "wattson", data_source: "Watts On", utility: "Aalborg Forsyning",
  utility_id: "aalborg-forsyning", portal_url: "https://aalborgforsyning.dk/services/forbrug/watts-on/",
  auto_sync: true, auto_sync_hour: 6, hourly: { kwh: Array(24).fill(2), period: "nov-2026 MTD (3 dage)" },
  billing: {}, forecast: {}, return_temp: { annual: { "2026": 32 }, monthly_2026: { Nov: 32 } },
  capabilities: ["auto_sync", "daily", "hourly", "monthly", "temperatures", "volume"],
};
calls = [];
card = render(W_ATTRS, calls);
html = card.shadowRoot.innerHTML;
assert.ok(sections(html).includes("hourly") && sections(html).includes("daily"), "Watts On hourly + daily shown");
assert.ok(html.includes("Data fra Watts On") && !html.includes("daglige aflæsninger"), "Watts On note, hourly");
assert.ok(!/MitID/.test(html) && !html.includes("Saldo"), "no MitID / billing for Watts On");
card.shadowRoot.getElementById("syncBtn").listeners.click();
assert.deepStrictEqual(calls.pop(), ["kmd_easy_energy", "sync", { entry_id: "e1" }], "Watts On uses sync service");

// 8) Watts On where heat field names were not recognised: only energy -> temps/volume/hourly hidden.
calls = [];
card = render(Object.assign({}, W_ATTRS, { hourly: {}, return_temp: {}, capabilities: ["auto_sync", "daily", "monthly"] }), calls);
html = card.shadowRoot.innerHTML;
const wsecs = sections(html);
assert.ok(!wsecs.includes("hourly") && !wsecs.includes("return-temp") && !wsecs.includes("ins-temp"), "unknown fields hidden");
assert.ok(wsecs.includes("daily") && wsecs.includes("monthly"), "energy still shown");

// 9) Watts On onboarding mentions the Watts On login (not forbrugernummer), no MitID wizard.
calls = [];
card = render(Object.assign({}, W_ATTRS, { initial_setup_complete: false, annual: {}, monthly: {}, daily: {} }), calls);
html = card.shadowRoot.innerHTML;
assert.ok(html.includes('id="efSyncBtn"') && html.includes("Watts On-konto"), "Watts On onboarding");
assert.ok(!html.includes("forbrugernummer") && !html.includes('id="mitidUserInput"'), "no E|Forsyning/MitID wording");
card = render({ capabilities: ALL_KMD, initial_setup_complete: false, annual: {}, monthly: {}, daily: {} }, []);
assert.ok(!card.shadowRoot.innerHTML.includes('value="aalborg-forsyning"'), "Aalborg not in MitID wizard");

// 10) E|Forsyning without cost capability shows calm price hint, ⚙️ panel saves price/expected return without MitID,
//     and single-target return temp (37/37) renders "Forventet retur (37°)".
calls = [];
card = render(Object.assign({}, EF_ATTRS, {
  utility_id: "middelfart-fjernvarme",
  utility: "Middelfart Fjernvarme",
  bonus_temp: 37,
  penalty_temp: 37,
  expected_return_temp: 37,
  capabilities: ["auto_sync", "daily", "monthly", "temperatures", "volume"],
}), calls);
html = card.shadowRoot.innerHTML;
assert.ok(html.includes('id="costHintSetupBtn"'), "shows price & expected return hint when cost capability absent");
assert.ok(html.includes("Forventet retur (37°)"), "single-target return temp chart title");
assert.ok(!html.includes('data-role="expected-return-curve"'), "no curve when expected_monthly data is absent");
assert.ok(!/MitID/.test(html), "no MitID wording on E|Forsyning view");
card.shadowRoot.getElementById("costHintSetupBtn").listeners.click();
html = card.shadowRoot.innerHTML;
assert.ok(html.includes('<details class="ob-manual" open>'), "settings details auto-opens when user clicks customize");
assert.ok(html.includes('id="efPriceInput"') && html.includes('id="efBonusInput"') && html.includes('id="efMotivPctInput"') && html.includes('id="saveTariffBtn"'), "shows quick price & expected return form");
assert.ok(!/MitID/.test(html), "no MitID wording in E|Forsyning settings panel");
card.shadowRoot.getElementById("efPriceInput").value = "0.705";
card.shadowRoot.getElementById("efBonusInput").value = "37";
card.shadowRoot.getElementById("efMotivPctInput").value = "1";
card.shadowRoot.getElementById("saveTariffBtn").listeners.click();
assert.deepStrictEqual(calls.pop(), [
  "kmd_easy_energy",
  "configure_utility",
  {
    complete_setup: true,
    entry_id: "e1",
    price_dkk_per_kwh: 0.705,
    motivation_pct_per_k: 1,
    bonus_temp: 37,
    penalty_temp: 37,
  },
]);

// 11) Multi-month Forv_Retur curve renders ONLY when expected_monthly data exists and user hasn't overridden thresholds.
calls = [];
card = render(Object.assign({}, EF_ATTRS, {
  utility_id: "middelfart-fjernvarme",
  utility: "Middelfart Fjernvarme",
  bonus_temp: 35,
  penalty_temp: 35,
  expected_return_temp: 35,
  expected_return_auto: true,
  return_temp: {
    annual: { "2026": 34.0 },
    monthly_2026: { Jan: 32.0, Feb: 35.0, Nov: 38.0 },
    expected_monthly_2026: { Jan: 33.0, Feb: 34.0, Nov: 37.0 },
  },
}), calls);
html = card.shadowRoot.innerHTML;
assert.ok(html.includes('data-role="expected-return-curve"'), "draws monthly Forv_Retur curve when data exists");
assert.ok(html.includes("33–37°"), "title shows Forv_Retur range");
assert.ok(html.includes("krav 37,0 °C"), "bar tooltip includes monthly expected return target");

// Advanced user override in card config hides the auto curve.
const cardOverride = new Card();
cardOverride.setConfig({ bonus_temp: 35, penalty_temp: 35 });
cardOverride.hass = mkHass(Object.assign({}, EF_ATTRS, {
  expected_return_auto: true,
  return_temp: {
    annual: { "2026": 34.0 },
    monthly_2026: { Jan: 32.0, Feb: 35.0, Nov: 38.0 },
    expected_monthly_2026: { Jan: 33.0, Feb: 34.0, Nov: 37.0 },
  },
}), []);
assert.ok(!cardOverride.shadowRoot.innerHTML.includes('data-role="expected-return-curve"'), "curve hidden when user explicitly overrides thresholds");

// 12) Auto-detection finds Danish *_overblik and suffixed *_overview_2 sensors instead of falling back to Kredsløb.
for (const entityId of ["sensor.hadsund_fjernvarme_overblik", "sensor.hadsund_fjernvarme_overview_2", "sensor.varme_hadsund"]) {
  const c = new Card();
  c.setConfig({});
  c.hass = {
    states: {
      [entityId]: {
        entity_id: entityId,
        state: "1234",
        attributes: Object.assign({}, EF_ATTRS, {
          utility: "Hadsund Fjernvarme",
          utility_id: "hadsund-fjernvarme",
          portal_url: "https://eforsyning.dk/hadsundfjernvarme/",
          initial_setup_complete: true,
          annual: { "2026": 1234 },
          monthly: { "2026": { Jan: 100 } },
          daily: { days: { "1": 10, "2": 11 }, month: "November 2026", total: 21, gennemsnit: 10.5 },
        }),
      },
    },
    services: { notify: {} },
    language: "da",
    connection: { subscribeMessage: () => Promise.resolve(() => {}) },
    callService: async () => {},
  };
  const out = c.shadowRoot.innerHTML;
  assert.strictEqual(c._resolveEntity()?.entity_id, entityId, `auto-detects ${entityId}`);
  assert.ok(out.includes("Data fra E|Forsyning"), `renders E|Forsyning dashboard for ${entityId}`);
  assert.ok(!out.includes("Førstegangsopsætning"), `does not fall back to Kredsløb wizard for ${entityId}`);
}

// 13) Desktop layout proportions, unified chart grid, theme contrast, and keyboard accessibility.
calls = [];
const kmdWide = render({ capabilities: ALL_KMD, backend: "kmd", hourly: { kwh: Array(24).fill(1) } }, calls);
const kmdHtml = kmdWide.shadowRoot.innerHTML;
assert.strictEqual((kmdHtml.match(/<div class="grid2">/g) || []).length, 1, "all chart panels share a single .grid2 container");
assert.ok(kmdHtml.includes('data-section="daily"') && kmdHtml.includes('viewBox="0 0 960 220"'), "5-chart desktop daily chart uses wide 960x220 viewBox");
assert.ok(kmdHtml.includes('id="syncTap" role="button" tabindex="0"'), "sync banner trigger is keyboard accessible");
assert.ok(kmdHtml.includes('tabindex="0" data-tip='), "SVG chart elements are keyboard focusable");
assert.ok(kmdHtml.includes('id="floatTip" role="tooltip"'), "floating tooltip container rendered");

// Enter key on syncTap triggers sync.
kmdWide.shadowRoot.getElementById("syncTap").listeners.keydown({ key: "Enter", preventDefault() {} });
assert.deepStrictEqual(calls.pop(), ["kmd_easy_energy", "sync", { entry_id: "e1" }], "Enter on syncTap triggers sync");

// Narrow viewport switches daily chart back to compact 540x220 viewBox.
const kmdNarrow = new Card();
kmdNarrow.clientWidth = 390;
kmdNarrow.setConfig({});
kmdNarrow.hass = mkHass({ capabilities: ALL_KMD, backend: "kmd", hourly: { kwh: Array(24).fill(1) } }, []);
assert.ok(kmdNarrow.shadowRoot.innerHTML.includes('viewBox="0 0 540 220"') && !kmdNarrow.shadowRoot.innerHTML.includes('viewBox="0 0 960 220"'), "narrow viewport keeps 540x220 daily viewBox");

// 4-chart E|Forsyning layout uses 2x2 grid (540x220 daily chart even on desktop).
const efDesktop = render(EF_ATTRS, []);
const efHtml = efDesktop.shadowRoot.innerHTML;
assert.strictEqual((efHtml.match(/<div class="grid2">/g) || []).length, 1, "E|Forsyning uses unified .grid2");
assert.ok(!efHtml.includes('viewBox="0 0 960 220"'), "4-chart 2x2 grid uses standard 540x220 daily viewBox");

// Settings dialog: separate notify label, .ob-pair without width:50% overflow, and Escape closes when setup complete.
kmdWide.shadowRoot.getElementById("openSetupBtn").listeners.click();
kmdWide._wizNotifyCustom = true;
kmdWide._render();
const wizHtml = kmdWide.shadowRoot.innerHTML;
assert.ok(wizHtml.includes('<label for="notifySel">'), "notifySel has explicit for= label");
assert.ok(!wizHtml.includes('style="width:50%"'), "paired inputs use CSS grid .ob-pair instead of overflowing width:50%");
assert.ok(wizHtml.includes('class="ob-pair"'), ".ob-pair class rendered");
kmdWide.shadowRoot.getElementById("onboardCard").listeners.keydown({ key: "Escape", preventDefault() {} });
assert.strictEqual(kmdWide._setupOpen, false, "Escape closes settings dialog");

// 14) Legacy eforsyning-custom entry with Hadsund portal URL upgrades to confirmed preset and infers discovered units in feedback.
const customHadsund = render({
  backend: "eforsyning",
  data_source: "E|Forsyning",
  utility: "Hadsund Fjernvarme a.m.b.a.",
  utility_id: "eforsyning-custom",
  utility_status: "pending_test",
  portal_url: "https://eforsyning.dk/hadsundfjernvarme/",
  available_units: [],
  capabilities: ["auto_sync", "cost", "daily", "monthly", "temperatures", "volume"],
  return_temp: { annual: { "2026": 31.2 }, monthly_2026: { Nov: 31.2 } },
}, []);
const chHtml = customHadsund.shadowRoot.innerHTML;
assert.ok(chHtml.includes("✅ Bekræftet"), "eforsyning-custom with Hadsund portal URL resolves to confirmed badge");
assert.ok(!chHtml.includes('id="fbGithubBtn"'), "unconfirmed feedback bar is hidden once upgraded to confirmed");
customHadsund.shadowRoot.getElementById("openSetupBtn").listeners.click();
let openedIssueUrl = "";
const prevOpen = global.window.open;
global.window.open = (u) => { openedIssueUrl = u; };
customHadsund.shadowRoot.getElementById("obFbGithubBtn").listeners.click();
global.window.open = prevOpen;
const decodedIssue = decodeURIComponent(openedIssueUrl);
assert.ok(decodedIssue.includes("Utility ID:** `hadsund-fjernvarme`"), "feedback report upgrades eforsyning-custom ID to hadsund-fjernvarme");
assert.ok(decodedIssue.includes("Discovered Units:** kWh, m3, °C"), "feedback report infers units when available_units is empty");

// 15) Hillerød Forsyning dynamic supply-temp penalty-only tariff: no 0° line/axis, no bonus text, and manual forward_temp input.
calls = [];
const hillerodCard = render({
  backend: "wattson",
  data_source: "Watts On",
  utility: "Hillerød Forsyning",
  utility_id: "hillerod-forsyning",
  utility_status: "confirmed",
  bonus_temp: 0,
  penalty_temp: 45,
  expected_return_temp: 45,
  expected_return_auto: true,
  forward_temp: 60.0,
  forward_temp_source: "meter",
  tariff: {
    price_dkk_per_kwh: 0.67,
    motivation_pct_per_k: 1.0,
    motivation_bonus: false,
    bonus_temp: 0,
    penalty_temp: 45,
    expected_return_by_forward_temp: [[58, 47], [68, 37]],
    forward_temp: 60.0,
    forward_temp_source: "meter",
  },
  capabilities: ["auto_sync", "cost", "daily", "hourly", "monthly", "temperatures", "volume"],
  annual: { "2026": 8000 },
  monthly: { "2026": { Jan: 1200, Jul: 200 } },
  daily: { month: "Nov 2026", days: { "24": 30 }, gennemsnit: 30, latest_complete: true, latest_date: "2026-11-24" },
  hourly: { period: "nov-2026 MTD", kwh: Array(24).fill(1.2), ret_temp: Array(24).fill(39.0) },
  return_temp: {
    annual: { "2026": 39.5 },
    monthly_2026: { Jan: 39.0, Jul: 41.0 },
    expected_monthly_2026: { Jan: 37.0, Jul: 47.0 },
  },
  cost_estimate: { effective_price_dkk_per_kwh: 0.67, base_price_dkk_per_kwh: 0.67, adjustment_pct: 0, current_month_dkk: 500, ytd_dkk: 5360 },
}, calls);
const hilHtml = hillerodCard.shadowRoot.innerHTML;
assert.ok(hilHtml.includes("Afkølingskrav (37–47°) · Dynamisk (fremløb)"), "shows dynamic cooling requirement range");
assert.ok(hilHtml.includes("OK (≤ krav)") && !hilHtml.includes("Under krav (bonus)"), "uses penalty-only legend");
assert.ok(hilHtml.includes("frem 60,0 °C"), "KPI shows current supply temperature");
assert.ok(!hilHtml.includes('class="ax-bonus">0°'), "does not render 0° bonus reference line when bonus_temp is 0");
const retSection = hilHtml.split('data-section="return-temp"')[1].split("</svg>")[0];
assert.ok(!retSection.includes(">0°</text>"), "return-temp chart has no 0° axis tick");
assert.ok(hilHtml.includes("krav ≤47,0 °C (OK — intet gebyr)"), "bar tooltip reflects penalty-only requirement");
hillerodCard.shadowRoot.getElementById("openSetupBtn").listeners.click();
const hilSetupHtml = hillerodCard.shadowRoot.innerHTML;
assert.ok(hilSetupHtml.includes('id="efForwardInput"'), "settings panel renders manual forward_temp input");
hillerodCard.shadowRoot.getElementById("efForwardInput").value = "70";
hillerodCard.shadowRoot.getElementById("saveTariffBtn").listeners.click();
assert.deepStrictEqual(calls.pop(), [
  "kmd_easy_energy",
  "configure_utility",
  {
    complete_setup: true,
    entry_id: "e1",
    forward_temp: 70,
  },
]);

// 16) Optional subscription / fixed fee fields and Expected annual cost KPI.
calls = [];
const feeCard = render({
  backend: "eforsyning",
  data_source: "E|Forsyning",
  utility: "Hedensted Fjernvarme",
  utility_id: "hedensted-fjernvarme",
  utility_status: "confirmed",
  tariff: {
    price_dkk_per_kwh: 0.93125,
    motivation_pct_per_k: 2.0,
    bonus_temp: 40,
    penalty_temp: 40,
    fixed_fee_dkk_per_m2_year: 41.5625,
    heated_area_m2: 162,
    fixed_fee_dkk_per_year: 787.5,
    annual_fixed_fee_dkk: 7520.62,
  },
  capabilities: ["auto_sync", "cost", "daily", "monthly", "temperatures", "volume"],
  cost_estimate: {
    base_price_dkk_per_kwh: 0.93125,
    effective_price_dkk_per_kwh: 0.93125,
    adjustment_pct: 0,
    latest_day_dkk: 58,
    latest_day_kwh: 40,
    latest_day_label: "24. Nov",
    current_month_dkk: 1239,
    current_month_kwh: 800,
    current_month_fixed_dkk: 494,
    ytd_dkk: 10500,
    ytd_fixed_dkk: 6700,
    annual_fixed_fee_dkk: 7520.62,
    forecast_annual_kwh: 12000,
    forecast_annual_dkk: 18696,
    excludes_fixed_fees: false,
  },
}, calls);
const feeHtml = feeCard.shadowRoot.innerHTML;
assert.ok(feeHtml.includes("💰 Estimeret udgift (2026)"), "title switches to Estimeret udgift when fixed fee is active");
assert.ok(feeHtml.includes("Inkl. fast bidrag (7.521 kr./år)"), "legend shows annual fixed fee");
assert.ok(feeHtml.includes("Forventet årsudgift"), "renders Expected annual cost KPI");
assert.ok(feeHtml.includes("~18.696 kr."), "renders expected annual cost value");
assert.ok(feeHtml.includes("12.000 kWh · inkl. 7.521 kr. fast"), "renders expected annual cost subtitle");
feeCard.shadowRoot.getElementById("openSetupBtn").listeners.click();
const feeSetupHtml = feeCard.shadowRoot.innerHTML;
assert.ok(feeSetupHtml.includes('id="efFixedM2Input"') && feeSetupHtml.includes('id="efAreaM2Input"') && feeSetupHtml.includes('id="efFixedYearInput"'), "renders fixed fee inputs in settings");
feeCard.shadowRoot.getElementById("efFixedM2Input").value = "33.75";
feeCard.shadowRoot.getElementById("efAreaM2Input").value = "162";
feeCard.shadowRoot.getElementById("efFixedYearInput").value = "787.5";
feeCard.shadowRoot.getElementById("saveTariffBtn").listeners.click();
assert.deepStrictEqual(calls.pop(), [
  "kmd_easy_energy",
  "configure_utility",
  {
    complete_setup: true,
    entry_id: "e1",
    fixed_fee_dkk_per_m2_year: 33.75,
    heated_area_m2: 162,
    fixed_fee_dkk_per_year: 787.5,
  },
]);

console.log("card_capabilities.test.js: OK");

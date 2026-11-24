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
assert.strictEqual(calls.pop()[1], "start_mitid_sync");

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

console.log("card_capabilities.test.js: OK");

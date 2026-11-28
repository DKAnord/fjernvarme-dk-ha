// Node harness: DanskForbrugCard (custom:dansk-forbrug-card) E2E tests (no real HA / network).
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

class FakeShadow {
  constructor() { this._html = ""; this.els = {}; this._detailNodes = []; this._closeNodes = []; }
  get innerHTML() { return this._html; }
  set innerHTML(val) {
    this._html = String(val || "");
    this.els = {};
    this._detailNodes = [];
    this._closeNodes = [];
    const seen = new Set();
    const re = /data-detail="([^"]+)"/g;
    let m;
    while ((m = re.exec(this._html)) !== null) {
      if (!seen.has(m[1])) {
        seen.add(m[1]);
        this._detailNodes.push({
          dataset: { detail: m[1] },
          listeners: {},
          addEventListener(ev, fn) { this.listeners[ev] = fn; },
        });
      }
    }
    const closeRe = /<button[^>]*data-modal-close="1"[^>]*>/g;
    while ((m = closeRe.exec(this._html)) !== null) {
      const idMatch = m[0].match(/id="([^"]+)"/);
      if (idMatch) {
        this._closeNodes.push(this.getElementById(idMatch[1]));
      } else {
        this._closeNodes.push({
          listeners: {},
          addEventListener(ev, fn) { this.listeners[ev] = fn; },
        });
      }
    }
  }
  getElementById(id) {
    if (!this._html.includes(`id="${id}"`)) return null;
    if (!this.els[id]) {
      this.els[id] = {
        id,
        value: "",
        children: [],
        listeners: {},
        appendChild(ch) { this.children.push(ch); },
        addEventListener(ev, fn) { this.listeners[ev] = fn; },
        setAttribute() {},
        style: {},
        classList: { add() {}, remove() {}, toggle() {} },
      };
    }
    return this.els[id];
  }
  querySelector() { return null; }
  querySelectorAll(sel) {
    if (sel === "[data-detail]") return this._detailNodes;
    if (sel === "[data-modal-close]") return this._closeNodes;
    return [];
  }
}

global.HTMLElement = class {
  constructor() { this._attrs = {}; this._events = []; }
  attachShadow() { this.shadowRoot = new FakeShadow(); return this.shadowRoot; }
  setAttribute(k, v) { this._attrs[k] = v; }
  dispatchEvent(ev) { this._events.push(ev); return true; }
};
global.CustomEvent = class {
  constructor(type, init) { this.type = type; Object.assign(this, init || {}); }
};
const defined = {};
global.customElements = { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } };
global.window = global;
global.document = { createElement: (tag) => new (defined[tag] || global.HTMLElement)() };
global.setInterval = () => 0;
global.clearInterval = () => {};

eval(fs.readFileSync(path.join(__dirname, "../../custom_components/kmd_easy_energy/frontend/kmd-easy-energy-card.js"), "utf8"));
const Card = defined["dansk-forbrug-card"];
const Editor = defined["dansk-forbrug-card-editor"];

const flush = () => new Promise((r) => setTimeout(r, 15));

function cphYmd(ms) {
  const fmt = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Copenhagen",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const parts = fmt.formatToParts(new Date(ms));
  const y = parts.find((p) => p.type === "year").value;
  const m = parts.find((p) => p.type === "month").value;
  const d = parts.find((p) => p.type === "day").value;
  return `${y}-${m}-${d}`;
}

function cphMidnightMs(ymd) {
  // Find exact UTC ms for 00:00 Europe/Copenhagen on YYYY-MM-DD.
  const [y, m, d] = ymd.split("-").map(Number);
  const guess = Date.UTC(y, m - 1, d, 0, 0, 0) - 3600000;
  for (let off = -3; off <= 3; off++) {
    const cand = guess + off * 3600000;
    const hr = Number(new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Copenhagen", hour: "2-digit", hour12: false }).format(new Date(cand)));
    if (cphYmd(cand) === ymd && hr === 0) return cand;
  }
  return guess;
}

async function run() {
  assert.ok(Card, "dansk-forbrug-card defined");
  assert.ok(Editor, "dansk-forbrug-card-editor defined");
  assert.ok(
    (global.window.customCards || []).some((c) => c.type === "dansk-forbrug-card"),
    "registered in window.customCards"
  );

  const nowMs = Date.now();
  const todayYmd = cphYmd(nowMs);
  const yestYmd = cphYmd(nowMs - 86400000);
  const day2Ymd = cphYmd(nowMs - 2 * 86400000);
  const day3Ymd = cphYmd(nowMs - 3 * 86400000);
  const curYr = todayYmd.slice(0, 4);
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"];
  const curMoKey = MONTHS[Number(todayYmd.slice(5, 7)) - 1];

  const baseStates = {
    "sensor.other_portal_overview": {
      entity_id: "sensor.other_portal_overview",
      state: "0",
      attributes: { portal_url: "https://other.example.dk/" },
    },
    "sensor.kredslob_overview": {
      entity_id: "sensor.kredslob_overview",
      state: "9500",
      attributes: {
        utility: "Kredsløb",
        utility_id: "kredslob",
        portal_url: "https://minvarme.kredslob.dk/",
        capabilities: ["billing", "cost", "daily", "forecast", "hourly", "monthly", "temperatures", "volume"],
        annual: { [curYr]: 9500 },
        daily: {
          days: { "1": 42, "2": 38, "3": 1 },
          latest_date: `${todayYmd.slice(0, 7)}-03`,
          latest_complete: false,
          gennemsnit: 40,
        },
        return_temp: {
          [`monthly_${curYr}`]: { [curMoKey]: 28.4 },
          thresholds: { bonus: 30, penalty: 40 },
        },
        insights: { kwh_per_hdd: { [curYr]: 4.12 }, temp_r2_pct: 91 },
        forecast: { expected_kwh: 11400, budget_kwh: 12000 },
        billing: { [`total_${curYr}_kr`]: 8200 },
        cost_estimate: {
          latest_day_kwh: 38.0,
          latest_day_dkk: 25,
          latest_day_label: `2. ${curMoKey.toLowerCase()} ${curYr}`,
          current_month_kwh: 920,
          current_month_dkk: 615,
          effective_price_dkk_per_kwh: 0.668,
          ytd_dkk: 6346,
        },
      },
    },
    "sensor.eloverblik_energy_statistic": {
      entity_id: "sensor.eloverblik_energy_statistic",
      state: "unknown",
      attributes: { unit_of_measurement: "kWh", state_class: "total", device_class: "energy" },
    },
    "sensor.stromligning_current_price_vat": {
      entity_id: "sensor.stromligning_current_price_vat",
      state: "2.15",
      attributes: {
        unit_of_measurement: "kr/kWh",
        prices: Array.from({ length: 24 }, (_, h) => ({
          start: `${todayYmd}T${String(h).padStart(2, "0")}:00:00+01:00`,
          price: h === 0 ? 1.85 : h === 17 ? 3.10 : (h >= 1 && h <= 3 ? 1.40 : 2.25),
        })),
      },
    },
    "sensor.stromligning_spotprice_vat": { entity_id: "sensor.stromligning_spotprice_vat", state: "1.65", attributes: {} },
    "sensor.stromligning_today_min_vat": { entity_id: "sensor.stromligning_today_min_vat", state: "1.80", attributes: {} },
    "sensor.stromligning_today_max_vat": { entity_id: "sensor.stromligning_today_max_vat", state: "3.15", attributes: {} },
    "binary_sensor.stromligning_tomorrow_available_vat": { entity_id: "binary_sensor.stromligning_tomorrow_available_vat", state: "on", attributes: {} },
    "sensor.stromligning_tomorrow_min_vat": { entity_id: "sensor.stromligning_tomorrow_min_vat", state: "1.42", attributes: {} },
    "sensor.ev_charger_energy": {
      entity_id: "sensor.ev_charger_energy",
      state: "1500.0",
      attributes: { unit_of_measurement: "kWh", state_class: "total_increasing", device_class: "energy" },
    },
    "sensor.eksempelvej_10_9999_by_12345678_water_meter_reading": {
      entity_id: "sensor.eksempelvej_10_9999_by_12345678_water_meter_reading",
      state: "410.25",
      attributes: {
        friendly_name: "eksempelvej 10 9999 by 12345678 Water Meter Reading",
        unit_of_measurement: "m³",
        device_class: "water",
        state_class: "total_increasing",
      },
    },
    "sensor.eksempelvej_10_9999_by_12345678_cold_water_energy_dashboard": {
      entity_id: "sensor.eksempelvej_10_9999_by_12345678_cold_water_energy_dashboard",
      state: "unknown",
      attributes: { unit_of_measurement: "m³", device_class: "water", state_class: "total_increasing" },
    },
    "sensor.eksempelvej_10_9999_by_12345678_min_flow": {
      entity_id: "sensor.eksempelvej_10_9999_by_12345678_min_flow",
      state: "0.0",
      attributes: { unit_of_measurement: "L/h" },
    },
    "sensor.eksempelvej_10_9999_by_12345678_max_flow": {
      entity_id: "sensor.eksempelvej_10_9999_by_12345678_max_flow",
      state: "210.0",
      attributes: { unit_of_measurement: "L/h" },
    },
  };

  // 1) getStubConfig auto-discovery
  const stub = Card.getStubConfig({ states: baseStates });
  assert.strictEqual(stub.entity, "sensor.kredslob_overview", "stub detects heat sensor");
  assert.strictEqual(stub.el_entity, "sensor.eloverblik_energy_statistic", "stub detects Eloverblik");
  assert.strictEqual(stub.el_price_entity, "sensor.stromligning_current_price_vat", "stub detects Stromligning");
  assert.strictEqual(
    stub.water_entity,
    "sensor.eksempelvej_10_9999_by_12345678_water_meter_reading",
    "stub detects water meter"
  );

  // 2) Full 3-column render via mocked recorder/statistics_during_period
  const wsCalls = [];
  const d3Mid = cphMidnightMs(day3Ymd);
  const d2Mid = cphMidnightMs(day2Ymd);
  const d1Mid = cphMidnightMs(yestYmd);
  const d0Mid = cphMidnightMs(todayYmd);

  const mockHourStats = {
    "sensor.eloverblik_energy_statistic": [
      { start: d3Mid + 2 * 3600000, change: 12.0 },
      { start: d3Mid + 12 * 3600000, change: 8.0 },
      { start: d2Mid + 3 * 3600000, change: 20.0 },
      { start: d2Mid + 14 * 3600000, change: 10.0 },
      // Trailing 0.0 placeholder day for Eloverblik lag — MUST be stripped!
      { start: d1Mid + 0 * 3600000, change: 0.0 },
      { start: d1Mid + 1 * 3600000, change: 0.0 },
    ],
    "sensor.stromligning_current_price_vat": [
      { start: d3Mid + 2 * 3600000, state: 1.50 },
      { start: d3Mid + 12 * 3600000, state: 2.50 },
      { start: d2Mid + 3 * 3600000, state: 2.00 },
      { start: d2Mid + 14 * 3600000, state: 3.00 },
    ],
    // EV charger reported 1 hour later (3+1=4h -> shifts -1h to 3h on d2!)
    "sensor.ev_charger_energy": [
      { start: d2Mid + 4 * 3600000, change: 15.0 },
    ],
  };

  const mockDayStats = {
    "sensor.eksempelvej_10_9999_by_12345678_cold_water_energy_dashboard": [
      { start: d3Mid, state: 409.500, change: 0.0 },
      // Simulate historical +397.478 change spike — state delta is 0.300 m³!
      { start: d2Mid, state: 409.800, change: 397.478 },
      { start: d1Mid, state: 410.200, change: 0.400 },
      { start: d0Mid, state: 410.250, change: 0.050 },
    ],
  };

  const hass3 = {
    states: baseStates,
    user: { id: "u1", is_admin: true },
    callWS: async (msg) => {
      wsCalls.push(msg);
      return msg.period === "hour" ? mockHourStats : mockDayStats;
    },
  };

  const card3 = new Card();
  card3.setConfig({
    entity: "sensor.kredslob_overview",
    el_entity: "sensor.eloverblik_energy_statistic",
    el_price_entity: "sensor.stromligning_current_price_vat",
    ev_entity: "sensor.ev_charger_energy",
    water_entity: "sensor.eksempelvej_10_9999_by_12345678_water_meter_reading",
    water_price_m3: 80.0,
  });
  card3.hass = hass3;
  await flush();

  const html3 = card3.shadowRoot.innerHTML;
  assert.strictEqual(card3._attrs["data-kmd-card-version"], "1.4.3", "sets version attribute");
  assert.strictEqual(wsCalls.length, 2, "issues hour and day WS queries");
  assert.ok(html3.includes("cols-3"), "3-column layout active");
  const d2Parts = day2Ymd.split("-");
  const expectedThru2 = `Eloverblik (t.o.m. ${Number(d2Parts[2])}/${Number(d2Parts[1])})`;
  assert.ok(html3.includes(expectedThru2), `shows Eloverblik data freshness (${expectedThru2})`);
  assert.ok(html3.includes("50,0 kWh") || html3.includes("30,0 kWh"), "renders Eloverblik kWh without placeholder zero day");
  assert.ok(!html3.includes(">0,0 kWh<"), "trailing 0.0 kWh placeholder day stripped");
  assert.ok(html3.includes("fill-ev"), "EV stacked bars rendered");
  assert.ok(html3.includes("Hus uden elbil (30d)"), "EV 30d baseline shown");
  assert.ok(html3.includes("Morgen fra 1,42") || html3.includes("I morgen fra 1,42"), "tomorrow min price shown");
  assert.ok(html3.includes("✅ Tæt (0 L/h min)"), "Målerportal min_flow tight badge shown");
  assert.ok(html3.includes('<div class="usub">Målerportal · 410,25 m³</div>'), "privacy-safe water subtitle uses Målerportal without address slug");
  assert.ok(html3.includes("410,25 m³"), "shows live meter reading m³");
  assert.ok(html3.includes("50 L"), "today water in liters via state delta");
  assert.ok(html3.includes("400 L"), "yesterday water in liters ignoring 397.478 spike");
  assert.ok(!html3.includes("397"), "spike value ignored");
  assert.ok(html3.includes("🎯 Retur 28,4 °C"), "KMD return temp shown");
  assert.ok(html3.includes("opkrævet 8.200 kr."), "KMD billing shown");
  assert.ok(html3.includes("prognose -5 % vs. budget"), "KMD forecast shown");
  assert.ok(!html3.includes("NaN") && !html3.includes("undefined"), "no NaN or undefined in 3-col output");

  // Leak warning when min_flow > 0
  const leakStates = {
    ...baseStates,
    "sensor.eksempelvej_10_9999_by_12345678_min_flow": {
      entity_id: "sensor.eksempelvej_10_9999_by_12345678_min_flow",
      state: "12.0",
      attributes: { unit_of_measurement: "L/h" },
    },
  };
  card3.hass = { ...hass3, states: leakStates };
  assert.ok(card3.shadowRoot.innerHTML.includes("⚠️ Min-flow 12 L/h!"), "leak alert badge shown");

  // 2b) Built-in plug-and-play detail modals (el, water, heat + close)
  card3.hass = hass3;
  const clickDetail = (kind) => {
    const btn = card3.shadowRoot.querySelectorAll("[data-detail]").find((b) => b.dataset.detail === kind);
    assert.ok(btn, `detail trigger ${kind} present`);
    btn.listeners.click();
  };

  clickDetail("el");
  let mHtml = card3.shadowRoot.innerHTML;
  assert.ok(mHtml.includes('data-modal="el"'), "opens el modal");
  assert.ok(mHtml.includes('id="dfModalBack"') && mHtml.includes("‹ Tilbage"), "el modal has top Back button");
  assert.ok(mHtml.includes("df-foot-back"), "el modal has footer Back button");
  assert.ok(mHtml.includes("Spot 1,65 + tarif/afgift 0,50 kr."), "renders spot + tariff breakdown");
  assert.ok(mHtml.includes("Billigste 3 timer"), "renders cheapest window KPI");
  assert.ok(mHtml.includes("pbars"), "renders hourly price bars");
  assert.ok(mHtml.includes("Seneste 30 dage elforbrug (kWh)"), "renders 30d electricity bars");

  clickDetail("water");
  mHtml = card3.shadowRoot.innerHTML;
  assert.ok(mHtml.includes('data-modal="water"'), "switches to water modal");
  assert.ok(mHtml.includes('id="dfModalBack"') && mHtml.includes("df-foot-back"), "water modal has Back buttons");
  assert.ok(mHtml.includes("Seneste 30 dage vandforbrug (liter/dag)"), "renders 30d water bars");
  assert.ok(mHtml.includes("✅ 0 L/h"), "shows leak status in water modal");

  clickDetail("heat");
  mHtml = card3.shadowRoot.innerHTML;
  assert.ok(mHtml.includes('data-modal="heat"'), "switches to heat modal");
  assert.ok(mHtml.includes('id="dfModalBack"') && mHtml.includes("df-foot-back"), "heat modal has top & footer Back buttons");
  const heatHost = card3.shadowRoot.getElementById("dfEmbeddedHeatHost");
  assert.ok(heatHost && heatHost.children.length === 1, "mounts embedded kmd-easy-energy-card");
  assert.strictEqual(heatHost.children[0]._config.entity, "sensor.kredslob_overview", "passes heat entity to embedded card");

  card3.shadowRoot.getElementById("dfModalBack").listeners.click();
  assert.ok(!card3.shadowRoot.innerHTML.includes("data-modal="), "back button dismisses modal");

  clickDetail("el");
  assert.ok(card3.shadowRoot.innerHTML.includes('data-modal="el"'), "re-opens modal");
  card3.shadowRoot.getElementById("dfModalClose").listeners.click();
  assert.ok(!card3.shadowRoot.innerHTML.includes("data-modal="), "close button dismisses modal");

  // 2c) Eloverblik auto-rescue from energy_total + hourly sensors when Recorder lags on yestYmd
  const rescueStates = {
    ...baseStates,
    "sensor.eloverblik_energy_total": {
      entity_id: "sensor.eloverblik_energy_total",
      state: "44.5",
      attributes: { metering_date: yestYmd, unit_of_measurement: "kWh" },
    },
  };
  for (let h = 0; h < 24; h++) {
    const val = h === 1 ? "20.0" : (h === 2 ? "24.5" : "0.0");
    rescueStates[`sensor.eloverblik_energy_${h}_${h + 1}`] = {
      entity_id: `sensor.eloverblik_energy_${h}_${h + 1}`,
      state: val,
      attributes: { metering_date: yestYmd, unit_of_measurement: "kWh" },
    };
  }
  const rescueCard = new Card();
  rescueCard.setConfig({
    entity: "sensor.kredslob_overview",
    el_entity: "sensor.eloverblik_energy_statistic",
    el_price_entity: "sensor.stromligning_current_price_vat",
    ev_entity: "sensor.ev_charger_energy",
    water_entity: "sensor.eksempelvej_10_9999_by_12345678_water_meter_reading",
  });
  rescueCard.hass = { ...hass3, states: rescueStates };
  await flush();
  const rHtml = rescueCard.shadowRoot.innerHTML;
  const yParts = yestYmd.split("-");
  assert.ok(rHtml.includes(`Eloverblik (t.o.m. ${Number(yParts[2])}/${Number(yParts[1])})`), "auto-rescue advances Eloverblik freshness date");
  assert.ok(rHtml.includes("44,5 kWh"), "auto-rescue recovers yestYmd total from energy_total + hourly sensors");

  // 3) E|Forsyning without billing, forecast, or temperatures capabilities
  const efCard = new Card();
  efCard.setConfig({});
  efCard.hass = {
    states: {
      "sensor.ef_overview": {
        entity_id: "sensor.ef_overview",
        state: "6400",
        attributes: {
          utility: "Middelfart Fjernvarme",
          utility_id: "middelfart-fjernvarme",
          portal_url: "https://eforsyning.dk/middelfartfjernvarme/",
          data_source: "E|Forsyning",
          capabilities: ["auto_sync", "cost", "daily", "monthly", "volume"],
          annual: { [curYr]: 6400 },
          daily: { days: { "1": 31, "2": 29 }, gennemsnit: 30 },
          insights: { kwh_per_hdd: { [curYr]: 3.85 }, temp_r2_pct: 86 },
          tariff: { price_dkk_per_kwh: 0.705, annual_fixed_fee_dkk: 1800 },
          cost_estimate: {
            latest_day_kwh: 29,
            latest_day_dkk: 20,
            latest_day_label: `2. ${curMoKey.toLowerCase()} ${curYr}`,
            current_month_kwh: 450,
            current_month_dkk: 317,
            effective_price_dkk_per_kwh: 0.705,
            ytd_dkk: 4512,
          },
        },
      },
    },
  };
  const efHtml = efCard.shadowRoot.innerHTML;
  assert.ok(efHtml.includes("cols-1"), "1-column layout when only Fjernvarme present");
  assert.ok(efHtml.includes("Middelfart Fjernvarme"), "shows utility name");
  assert.ok(!efHtml.includes("Returtemperatur"), "hides return temp without temperatures capability");
  assert.ok(!efHtml.includes("opkrævet"), "hides billing without billing capability");
  assert.ok(!efHtml.includes("vs. budget"), "hides forecast without forecast capability");
  assert.ok(efHtml.includes("fast bidrag ~1.800 kr./år"), "shows fixed fee when present");
  assert.ok(!efHtml.includes("NaN") && !efHtml.includes("undefined"), "no NaN or undefined in E|Forsyning output");

  // 4) Live P1 meter + Energi Data Service (mean LTS + raw_today/raw_tomorrow), NO EV, NO Water -> cols-2
  const p1Card = new Card();
  p1Card.setConfig({
    entity: "sensor.ef_overview",
    el_entity: "sensor.watts_live_grid_import",
    el_price_entity: "sensor.energi_data_service",
  });
  p1Card.hass = {
    states: {
      "sensor.ef_overview": efCard._hass.states["sensor.ef_overview"],
      "sensor.watts_live_grid_import": {
        entity_id: "sensor.watts_live_grid_import",
        state: "4521.4",
        attributes: { friendly_name: "Elmåler", unit_of_measurement: "kWh", device_class: "energy", state_class: "total_increasing" },
      },
      "sensor.energi_data_service": {
        entity_id: "sensor.energi_data_service",
        state: "2.45",
        attributes: {
          unit_of_measurement: "DKK/kWh",
          raw_today: [{ price: 1.90 }, { price: 2.80 }],
          tomorrow_valid: true,
          raw_tomorrow: [{ price: 1.55 }, { price: 2.10 }],
        },
      },
    },
    callWS: async () => ({
      "sensor.watts_live_grid_import": [
        { start: d1Mid + 8 * 3600000, change: 10.0 },
        { start: d0Mid + 7 * 3600000, change: 4.5 },
      ],
      "sensor.energi_data_service": [
        { start: d1Mid + 8 * 3600000, mean: 2.00 },
        { start: d0Mid + 7 * 3600000, mean: 2.50 },
      ],
    }),
  };
  await flush();
  const p1Html = p1Card.shadowRoot.innerHTML;
  assert.ok(p1Html.includes("cols-2"), "2-column layout without water");
  assert.ok(!p1Html.includes('data-section="water"'), "no water section rendered");
  assert.ok(!p1Html.includes("Elbil"), "no EV text rendered without ev_entity");
  assert.ok(p1Html.includes("Energi Data Service"), "auto-detects Energi Data Service subtitle");
  assert.ok(p1Html.includes("1,90–2,80 kr."), "reads EDS raw_today min/max");
  assert.ok(p1Html.includes("I morgen fra 1,55 kr."), "reads EDS raw_tomorrow min");
  assert.ok(p1Html.includes("4,5"), "includes today's live P1 bar");

  // 5) DanskForbrugCardEditor emits clean config-changed events
  const ed = new Editor();
  ed.setConfig({ language: "da", el_entity: "sensor.old" });
  ed.hass = { states: baseStates };
  ed.shadowRoot.getElementById("df_el_entity").listeners.change({ target: { value: "sensor.eloverblik_energy_statistic" } });
  ed.shadowRoot.getElementById("df_water_price_m3").listeners.change({ target: { value: "75" } });
  ed.shadowRoot.getElementById("df_ev_entity").listeners.change({ target: { value: "" } });
  assert.strictEqual(ed._events.length, 3, "editor emitted 3 config-changed events");
  const lastCfg = ed._events[2].detail.config;
  assert.strictEqual(lastCfg.el_entity, "sensor.eloverblik_energy_statistic");
  assert.strictEqual(lastCfg.water_price_m3, 75);
  assert.ok(!("ev_entity" in lastCfg), "empty optional string removed from config");

  console.log("card_dansk_forbrug.test.js: OK");
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});

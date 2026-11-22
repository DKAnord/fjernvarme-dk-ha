// Node harness: outdoor temperature source line (no real HA / network).
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

const render = (attrs, calls) => { const c = new Card(); c.setConfig({}); c.hass = mkHass(attrs, calls || []); return c; };
const ALL_KMD = ["billing", "cost", "daily", "forecast", "hourly", "mitid", "monthly", "reminder", "temperatures", "volume"];
const WX = { monthly_temp: { "2026-10": 9.1 }, daily_temp: { "2026-11-20": 4.2 } };
const note = (attrs) => {
  const html = render(Object.assign({ capabilities: ALL_KMD, backend: "kmd", weather: WX }, attrs)).shadowRoot.innerHTML;
  const m = /data-section="temp-source">([^<]*)</.exec(html);
  return m ? m[1] : null;
};

// 1) HA sensor only.
assert.strictEqual(
  note({ temp_source: "ha_sensor", outdoor_temp: { source: "ha_sensor", entity_id: "sensor.ude", sensor_name: "Udetermometer" } }),
  "🌡️ Udetemp: Udetermometer",
);
// Falls back to the entity id when the name is unknown; names are HTML-escaped.
assert.strictEqual(note({ temp_source: "ha_sensor", outdoor_temp: { entity_id: "sensor.ude" } }), "🌡️ Udetemp: sensor.ude");
assert.ok(note({ temp_source: "ha_sensor", outdoor_temp: { sensor_name: "<b>x</b>" } }).includes("&lt;b&gt;x&lt;/b&gt;"));

// 2) Open-Meteo at HA home / utility / custom location.
assert.strictEqual(note({ temp_source: "open_meteo_home", outdoor_temp: { configured_location: "home" } }), "🌡️ Udetemp: Open-Meteo (HA-hjemmelokation)");
assert.strictEqual(note({ temp_source: "open_meteo_utility" }), "🌡️ Udetemp: Open-Meteo (værkets placering)");
assert.strictEqual(note({ temp_source: "open_meteo_custom" }), "🌡️ Udetemp: Open-Meteo (egen placering)");

// 3) Mixed: sensor since a date, Open-Meteo before.
assert.strictEqual(
  note({ temp_source: "mixed", outdoor_temp: { sensor_name: "Udetermometer", sensor_since: "2026-03-05", open_meteo_location: "home" } }),
  "🌡️ Udetemp: Udetermometer fra 5. mar 2026; dage uden sensorstatistik: Open-Meteo (HA-hjemmelokation)",
);

// 4) Sensor configured but without long-term statistics; pending change.
assert.strictEqual(
  note({ temp_source: "open_meteo_home", outdoor_temp: { entity_id: "sensor.ude", sensor_name: "Ude", sensor_status: "no_statistics" } }),
  "🌡️ Udetemp: Open-Meteo (HA-hjemmelokation) · Ude har endnu ingen langtidsstatistik",
);
assert.ok(note({ temp_source: "open_meteo_home", outdoor_temp: { pending: true } }).endsWith("opdateres ved næste synkronisering"));

// 5) Capability-driven: hidden without temperature data, without a source, or
//    when the backend shows neither monthly nor daily sections.
assert.strictEqual(note({ temp_source: "open_meteo_home", weather: {} }), null);
assert.strictEqual(note({ temp_source: null }), null);
assert.strictEqual(note({ temp_source: "open_meteo_home", capabilities: ["hourly", "cost"] }), null);
// Unknown attributes (e.g. stray coordinates) are never rendered in the line.
const odd = note({ temp_source: "open_meteo_home", outdoor_temp: { configured_location: "home", latitude: 56.987654, longitude: 10.123456 } });
assert.ok(!odd.includes("56.98") && !odd.includes("10.12"), "no coordinates in the source line");

// 6) English card language.
const c = new Card(); c.setConfig({ language: "en" });
c.hass = mkHass({ capabilities: ALL_KMD, weather: WX, temp_source: "open_meteo_utility" }, []);
assert.ok(c.shadowRoot.innerHTML.includes("Outdoor temp: Open-Meteo (utility location)"));

console.log("card_outdoor_temp.test.js: OK");

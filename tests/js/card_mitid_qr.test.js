// Node harness: card shows MitID QR from the websocket subscription and
// alternates both frames every second (no real HA, no real MitID).
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const els = {};
const mkEl = (id) => ({ id, src: "", value: "", checked: false, style: {}, addEventListener() {}, setAttribute() {}, classList: { add() {}, remove() {}, toggle() {} } });
class FakeShadow {
  constructor() { this._html = ""; }
  set innerHTML(h) { this._html = h; for (const k of Object.keys(els)) delete els[k]; }
  get innerHTML() { return this._html; }
  getElementById(id) {
    if (!this._html.includes(`id="${id}"`)) return null;
    if (!els[id]) {
      els[id] = mkEl(id);
      const m = this._html.match(new RegExp(`id="${id}"[^>]*src="([^"]*)"`));
      if (m) els[id].src = m[1].replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
    }
    return els[id];
  }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
global.HTMLElement = class { attachShadow() { this.shadowRoot = new FakeShadow(); return this.shadowRoot; } };
const defined = {};
global.customElements = { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } };
global.window = global;
global.document = { createElement: () => ({}) };

// Fake timers
let timers = [];
global.setInterval = (fn, ms) => { const t = { fn, ms }; timers.push(t); return t; };
global.clearInterval = (t) => { timers = timers.filter((x) => x !== t); };

const src = fs.readFileSync(path.join(__dirname, "../../custom_components/kmd_easy_energy/frontend/kmd-easy-energy-card.js"), "utf8");
eval(src);
const Card = defined["kmd-easy-energy-card"];
assert.ok(Card, "card defined");

let subCb = null, subMsg = null;
const hass = {
  states: {
    "sensor.kredslob_overview": {
      entity_id: "sensor.kredslob_overview", state: "0",
      attributes: { utility_id: "kredslob", entry_id: "e1", portal_url: "https://minvarme.kredslob.dk/", initial_setup_complete: false },
    },
  },
  services: { notify: {} },
  language: "da",
  connection: {
    subscribeMessage: (cb, msg) => { subCb = cb; subMsg = msg; return Promise.resolve(() => {}); },
    subscribeEvents: () => { throw new Error("must not use subscribeEvents (admin-only, recorded bus)"); },
  },
  callService: async () => {},
};

const card = new Card();
card.setConfig({});
card.hass = hass;
assert.deepStrictEqual(subMsg, { type: "kmd_easy_energy/mitid/subscribe" });

const html0 = card.shadowRoot.innerHTML;
assert.ok(html0.includes("Kun hvis du opsætter på samme telefon som MitID-appen"), "new heading");
assert.ok(!html0.includes("headless browser"), "old claim removed");
assert.ok(!html0.includes("Vigtigt for nye brugere"), "old heading removed");

const f1 = '<svg viewBox="0 0 3 3"><path d="M0,0H1V1H0z"/></svg>';
const f2 = '<svg viewBox="0 0 3 3"><path d="M1,1H2V2H1z"/></svg>';
// Event for another entry is ignored
subCb({ entry_id: "other", sync_state: "qr_ready", qr_frames: [f1, f2] });
assert.ok(!card.shadowRoot.innerHTML.includes('id="mitidQrImg"'));

subCb({ entry_id: "e1", sync_state: "qr_ready", otp_code: null, qr_frames: [f1, f2] });
let html = card.shadowRoot.innerHTML;
assert.ok(html.includes('id="mitidQrImg"'), "QR img rendered");
assert.ok(html.includes("Scan QR-koden med MitID-appen på din telefon"));
const img = card.shadowRoot.getElementById("mitidQrImg");
assert.strictEqual(decodeURIComponent(img.src.split("utf8,")[1]), f1);
assert.strictEqual(timers.length, 1, "one animation timer");
assert.strictEqual(timers[0].ms, 1000);
timers[0].fn();
assert.strictEqual(decodeURIComponent(card.shadowRoot.getElementById("mitidQrImg").src.split("utf8,")[1]), f2, "frame 2");
timers[0].fn();
assert.strictEqual(decodeURIComponent(card.shadowRoot.getElementById("mitidQrImg").src.split("utf8,")[1]), f1, "back to frame 1");

// Verified: QR disappears, timer stops, no code required
subCb({ entry_id: "e1", sync_state: "verified", otp_code: null, qr_frames: [] });
assert.ok(!card.shadowRoot.innerHTML.includes('id="mitidQrImg"'));
assert.strictEqual(timers.length, 0, "timer stopped");

// OTP path still works
subCb({ entry_id: "e1", sync_state: "otp_ready", otp_code: "4821", qr_frames: [] });
assert.ok(card.shadowRoot.innerHTML.includes("4 8 2 1"));

card.disconnectedCallback();
assert.strictEqual(timers.length, 0);
console.log("card_mitid_qr.test.js: OK");

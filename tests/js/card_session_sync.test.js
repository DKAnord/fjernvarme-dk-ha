// Node harness: session-based sync card behaviour (no real HA / MitID).
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

// 1) Reminder active -> banner shows Danish reminder message, no token wording.
let calls = [];
let card = new Card();
card.setConfig({});
card.hass = mkHass({ last_sync: "2026-11-17T08:00:00+00:00", sync_reminder: true, sync_reminder_message: "Det er 4 dage siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik.", days_since_sync: 4 }, calls);
let html = card.shadowRoot.innerHTML;
assert.ok(html.includes("Det er 4 dage siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik."), "friendly nudge");
// Calm chip placed right after the banner with the Synkroniser button, no alarm styling.
const nudgeIdx = html.indexOf('class="sync-nudge"');
const btnIdx = html.indexOf('id="syncBtn"');
assert.ok(nudgeIdx > btnIdx && nudgeIdx - btnIdx < 600, "nudge near Synkroniser button");
const nudgeHtml = html.slice(nudgeIdx, html.indexOf("</div>", nudgeIdx));
assert.ok(!/red|ob-live|⚠|Fejl/.test(nudgeHtml), "no error styling");
assert.ok(!/bn-ico (red|amber)/.test(html), "banner icon not alarmed by reminder");
const css = html.slice(html.indexOf(".sync-nudge {"), html.indexOf("}", html.indexOf(".sync-nudge {")));
assert.ok(!/239,68,68|#dc2626|245,158,11/.test(css), "nudge uses calm colours");
assert.ok(html.includes("Sidst synkroniseret 17. nov"), "last synced label");
assert.ok(!/Token udløbet/.test(html), "no token-expired wording");

// 2) Sync button always starts a sync via kmd_easy_energy.sync (non-admin wall tablet compatible, never cache 'refresh').
card.shadowRoot.getElementById("syncBtn").listeners.click();
assert.deepStrictEqual(calls[calls.length - 1], ["kmd_easy_energy", "sync", { entry_id: "e1" }]);

// 2b) Non-admin wall tablet hides setup/settings buttons while sync still calls kmd_easy_energy.sync.
const nonAdminCalls = [];
const tabletCard = new Card();
tabletCard.setConfig({});
const tabletHass = mkHass({ last_sync: "2026-11-20T08:00:00+00:00", sync_reminder: false }, nonAdminCalls);
tabletHass.user = { is_admin: false };
tabletCard.hass = tabletHass;
const tabletHtml = tabletCard.shadowRoot.innerHTML;
assert.ok(!tabletHtml.includes('id="openSetupBtn"'), "non-admin hides setup button");
assert.ok(!tabletHtml.includes('id="costHintSetupBtn"'), "non-admin hides cost-hint setup button");
tabletCard.shadowRoot.getElementById("syncBtn").listeners.click();
assert.deepStrictEqual(nonAdminCalls.pop(), ["kmd_easy_energy", "sync", { entry_id: "e1" }]);

// 3) No reminder -> normal banner without reminder text.
calls = [];
card = new Card();
card.setConfig({});
card.hass = mkHass({ last_sync: "2026-11-20T08:00:00+00:00", sync_reminder: false, sync_reminder_message: "", days_since_sync: 1 }, calls);
html = card.shadowRoot.innerHTML;
assert.ok(!html.includes('class="sync-nudge"'), "no reminder chip");
assert.ok(html.includes("Synkroniser fjernvarme (MitID)") || html.includes("Synkroniseret i dag"));

// 4) Onboarding text explains the session model; manual token is one-shot.
card = new Card();
card.setConfig({});
card.hass = mkHass({ initial_setup_complete: false, annual: {}, monthly: {}, daily: {} }, calls);
html = card.shadowRoot.innerHTML;
assert.ok(html.includes("Hver synkronisering er ét MitID-login"), "session explanation");
assert.ok(html.includes("gemmes ikke"), "token not stored");
assert.ok(html.includes("Synkroniser én gang med token"));

// 5) Feedback report splits Card Version vs Integration Version and sanitizes sync diagnostics on Issue.
const opened = [];
global.window.open = (url) => { opened.push(url); };
card = new Card();
card.setConfig({});
card.hass = mkHass({
  utility_id: "struer-energi",
  utility_status: "pending_test",
  integration_version: "1.3.21",
  sync_state: "error",
  sync_message: "Fejl for anna@example.com med token abcdefghijklmnopqrstuvwxyz123456",
}, calls);
card.shadowRoot.getElementById("fbIssueBtn").listeners.click();
assert.strictEqual(opened.length, 1);
const issueUrl = new URL(opened[0]);
const issueBody = issueUrl.searchParams.get("body");
assert.ok(issueBody.includes("- **Card Version:** 1.3.21"), "issue includes Card Version");
assert.ok(issueBody.includes("- **Integration Version:** 1.3.21"), "issue includes Integration Version");
assert.ok(issueBody.includes("- **Sync State:** `error`"), "issue includes Sync State");
assert.ok(issueBody.includes("- **Last Sync Message:** Fejl for [email] med token [redacted]"), "issue sanitizes sync message");
assert.ok(!issueBody.includes("anna@example.com"), "issue does not leak email");
assert.ok(!issueBody.includes("abcdefghijklmnopqrstuvwxyz123456"), "issue does not leak raw token");

card.shadowRoot.getElementById("fbGithubBtn").listeners.click();
assert.strictEqual(opened.length, 2);
const confirmedUrl = new URL(opened[1]);
const confirmedBody = confirmedUrl.searchParams.get("body");
assert.ok(confirmedBody.includes("- **Card Version:** 1.3.21"), "confirmed includes Card Version");
assert.ok(confirmedBody.includes("- **Integration Version:** 1.3.21"), "confirmed includes Integration Version");
assert.ok(!confirmedBody.includes("Sync State:"), "confirmed omits Sync State");
assert.ok(!confirmedBody.includes("Last Sync Message:"), "confirmed omits Last Sync Message");

console.log("card_session_sync.test.js: OK");

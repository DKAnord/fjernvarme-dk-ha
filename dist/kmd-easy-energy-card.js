/* KMD Easy Energy Card – Plug-and-Play District Heating Dashboard & Visual Editor
 * Supports any utility on easy-energy-plugin-api.kmd.dk (and legacy sensor.kredslob_varme).
 * Zero external dependencies, Shadow DOM, responsive, interactive tooltips, DA/EN i18n.
 */
(() => {
  const VER = "1.3.1";
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"];
  const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const isLeapYear = (y) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  const daysInMonth = (mIdx, yr) => (mIdx === 1 && isLeapYear(yr) ? 29 : DAYS_IN_MONTH[mIdx] || 30);

  const identifyPeakHours = (kwh) => {
    const valid = (Array.isArray(kwh) ? kwh : []).filter((v) => typeof v === "number" && Number.isFinite(v) && v > 0);
    if (valid.length < 4) {
      return { peaks: new Set(), peakList: [], median: 0, maxVal: 0, maxIdx: 0, minPos: 0 };
    }
    const s = [...valid].sort((a, b) => a - b);
    const n = s.length;
    const mid = Math.floor(n / 2);
    const median = n % 2 === 1 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
    const q25 = s[Math.floor(n * 0.25)];
    const q75 = s[Math.floor(n * 0.75)];
    const iqr = q75 - q25;
    const absDev = s.map((v) => Math.abs(v - median)).sort((a, b) => a - b);
    const mad = n % 2 === 1 ? absDev[mid] : (absDev[mid - 1] + absDev[mid]) / 2;
    let sigma = Math.max(1.4826 * mad, iqr / 1.349);
    if (sigma === 0) {
      const mean = s.reduce((a, b) => a + b, 0) / n;
      sigma = Math.sqrt(s.reduce((a, v) => a + (v - mean) ** 2, 0) / n);
    }
    const maxVal = s[n - 1];
    const minPos = s[0];
    const maxIdx = kwh.indexOf(maxVal);
    if (maxVal <= 0 || (maxVal - median) < Math.max(0.05, median * 0.05)) {
      return { peaks: new Set(), peakList: [], median, maxVal, maxIdx, minPos };
    }
    const thresh = Math.max(
      median + Math.max(1.0 * sigma, median * 0.10),
      median + 0.55 * (maxVal - median)
    );
    let candidates = [];
    kwh.forEach((v, h) => {
      if (typeof v === "number" && Number.isFinite(v) && v >= thresh) {
        candidates.push([h, v]);
      }
    });
    if (candidates.length === 0 && maxVal >= median * 1.08) {
      kwh.forEach((v, h) => {
        if (typeof v === "number" && Number.isFinite(v) && v >= maxVal - 1e-6) {
          candidates.push([h, v]);
        }
      });
    }
    candidates.sort((a, b) => (b[1] - a[1]) || (a[0] - b[0]));
    const top = candidates.slice(0, 4);
    return {
      peaks: new Set(top.map((c) => c[0])),
      peakList: top.map((c) => c[0]).sort((a, b) => a - b),
      median,
      maxVal,
      maxIdx,
      minPos,
    };
  };

  const niceStep = (maxV, targetTicks = 4) => {
    if (maxV <= 0) return 1;
    const raw = maxV / targetTicks;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    if (norm <= 1) return mag;
    if (norm <= 2) return 2 * mag;
    if (norm <= 2.5) return 2.5 * mag;
    if (norm <= 5) return 5 * mag;
    return 10 * mag;
  };

  const UTILITIES = [
    { id: "kredslob", name: "Kredsløb", city: "Aarhus", url: "https://minvarme.kredslob.dk/", status: "confirmed" },
    { id: "galten-varmevaerk", name: "Galten Varmeværk", city: "Galten", url: "https://minvarme.kredslob.dk/", status: "pending_test" },
    { id: "energi-ikast", name: "Energi Ikast", city: "Ikast", url: "https://energi-ikast.dk/", status: "confirmed" },
    { id: "struer-energi", name: "Struer Energi", city: "Struer", url: "https://struerenergi.dk/selvbetjening/", status: "pending_test" },
    { id: "envafors", name: "Envafors / SK Forsyning", city: "Slagelse / Næstved", url: "https://skenergi.dk/minforsyning/", status: "pending_test" },
    { id: "frederikshavn-forsyning", name: "Frederikshavn Forsyning", city: "Frederikshavn", url: "https://www.forsyningen.dk/selvbetjening", status: "confirmed" },
    { id: "vestforsyning", name: "Vestforsyning", city: "Holstebro", url: "https://www.vestforsyning.dk/selvbetjening/", status: "pending_test" },
    { id: "beof", name: "Bornholms Energi & Forsyning", city: "Bornholm", url: "https://minforsyning.beof.dk/", status: "confirmed" },
    { id: "kalundborg-forsyning", name: "Kalundborg Forsyning", city: "Kalundborg", url: "https://kalfor.dk/selvbetjening/min-forsyning", status: "confirmed" },
    { id: "albertslund-forsyning", name: "Albertslund Forsyning", city: "Albertslund", url: "https://forsyning.albertslund.dk/selvbetjening", status: "confirmed" },
    { id: "nykobing-sj", name: "Nykøbing Sjælland Varmeværk", city: "Odsherred", url: "https://www.nsfv.dk/", status: "pending_test" },
    { id: "forsyning-helsingor", name: "Forsyning Helsingør", city: "Helsingør", url: "https://www.fh.dk/watts", status: "pending_test", backend: "wattson" },
    { id: "soroe-fjernvarme", name: "Sorø Fjernvarme", city: "Sorø", url: "https://eforsyning.dk/soroe/", status: "confirmed", backend: "eforsyning" },
    { id: "middelfart-fjernvarme", name: "Middelfart Fjernvarme", city: "Middelfart", url: "https://eforsyning.dk/middelfartfjernvarme/", status: "confirmed", backend: "eforsyning" },
    { id: "hadsund-fjernvarme", name: "Hadsund Fjernvarme", city: "Hadsund", url: "https://eforsyning.dk/hadsundfjernvarme/", status: "confirmed", backend: "eforsyning" },
    { id: "hedensted-fjernvarme", name: "Hedensted Fjernvarme", city: "Hedensted", url: "https://eforsyning.dk/hedenstedfjernvarme/", status: "confirmed", backend: "eforsyning" },
    { id: "dronninglund-fjernvarme", name: "Dronninglund Fjernvarme", city: "Dronninglund", url: "https://eforsyning.dk/dronninglundfjernvarme/", status: "confirmed", backend: "eforsyning" },
    { id: "hjorring-varmeforsyning", name: "Hjørring Varmeforsyning", city: "Hjørring", url: "https://eforsyning.dk/hjvarme/", status: "pending_test", backend: "eforsyning" },
    { id: "aalborg-forsyning", name: "Aalborg Forsyning", city: "Aalborg", url: "https://aalborgforsyning.dk/services/forbrug/watts-on/", status: "confirmed", backend: "wattson" },
    { id: "fjernvarme-fyn", name: "Fjernvarme Fyn", city: "Odense / Fyn", url: "https://www.fjernvarmefyn.dk/spar-paa-energien/overblik/watts-on-app/", status: "confirmed", backend: "wattson" },
    { id: "hillerod-forsyning", name: "Hillerød Forsyning", city: "Hillerød", url: "https://hfors.dk/selvbetjening/se-forbrug-regninger/watts-on-din-forbrugsapp-til-vand-varme", status: "confirmed", backend: "wattson" },
  ];

  const I18N = {
    da: {
      confirmed: "✅ Bekræftet",
      pending: "🧪 Afventer 1. test",
      confirmed_grp: "✅ Bekræftet (Confirmed Working)",
      pending_grp: "🧪 Afventer første test (Pending Initial Test)",
      login_btn: "🔑 Log ind på værk ↗",
      sync_btn: "🔄 Synkroniser",
      last_sync: "Sidst synkroniseret",
      never_synced: "Ikke synkroniseret endnu",
      kpi_ytd: "🔥 Forbrug",
      kpi_ret: "🌡️ Returtemperatur",
      kpi_fc: "📉 Prognose",
      kpi_bill: "💳 Regninger",
      outdoor: "Ude",
      avg_day: "kWh/dag",
      tip_hint: "Tryk eller hold musen over en søjle/prik for tal",
      no_daily: "Ingen daglige data endnu",
    },
    en: {
      confirmed: "✅ Confirmed",
      pending: "🧪 Pending test",
      confirmed_grp: "✅ Confirmed Working",
      pending_grp: "🧪 Pending Initial Test",
      login_btn: "🔑 Utility Login ↗",
      sync_btn: "🔄 Sync",
      last_sync: "Last synced",
      never_synced: "Not synced yet",
      kpi_ytd: "🔥 Consumption",
      kpi_ret: "🌡️ Return temp",
      kpi_fc: "📉 Forecast",
      kpi_bill: "💳 Billing",
      outdoor: "Outdoor",
      avg_day: "kWh/day",
      tip_hint: "Tap or hover a bar/point for details",
      no_daily: "No daily data yet",
    },
  };

  // Outdoor temperature source line (integration attribute temp_source /
  // outdoor_temp; location kind only, never coordinates). "" = nothing to show.
  const fmtIsoDay = (iso) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    return m ? `${Number(m[3])}. ${(MONTHS[Number(m[2]) - 1] || "").toLowerCase()} ${m[1]}` : "";
  };
  const outdoorTempText = (a, lang) => {
    const ot = (a && typeof a.outdoor_temp === "object" && a.outdoor_temp) || {};
    const src = (a && a.temp_source) || ot.source || "";
    if (!src) return "";
    const en = lang === "en";
    const sensor = ot.sensor_name || ot.entity_id || (en ? "HA sensor" : "HA-sensor");
    const loc = ot.open_meteo_location || ot.configured_location || "";
    const meteo = {
      home: en ? "Open-Meteo (HA home location)" : "Open-Meteo (HA-hjemmelokation)",
      utility: en ? "Open-Meteo (utility location)" : "Open-Meteo (værkets placering)",
      custom: en ? "Open-Meteo (custom location)" : "Open-Meteo (egen placering)",
    };
    const meteoBySrc = { open_meteo_home: meteo.home, open_meteo_utility: meteo.utility, open_meteo_custom: meteo.custom, open_meteo: "Open-Meteo" };
    const lbl = en ? "Outdoor temp" : "Udetemp";
    let txt;
    if (src === "ha_sensor") txt = `${lbl}: ${sensor}`;
    else if (src === "mixed") {
      const since = fmtIsoDay(ot.sensor_since);
      const before = meteo[loc] || "Open-Meteo";
      txt = en
        ? `${lbl}: ${sensor}${since ? ` from ${since}` : ""}; days without sensor statistics: ${before}`
        : `${lbl}: ${sensor}${since ? ` fra ${since}` : ""}; dage uden sensorstatistik: ${before}`;
    } else txt = `${lbl}: ${meteoBySrc[src] || "Open-Meteo"}`;
    if (src !== "ha_sensor" && src !== "mixed" && ot.entity_id && ot.sensor_status && ot.sensor_status !== "ok") {
      txt += en ? ` · ${sensor} has no long-term statistics yet` : ` · ${sensor} har endnu ingen langtidsstatistik`;
    }
    if (ot.pending) txt += en ? " · updates at next sync" : " · opdateres ved næste synkronisering";
    return txt;
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtInt = (n) => Number.isFinite(n) ? Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".") : "–";
  const fmtDec = (n, d = 1) => Number.isFinite(n) ? n.toFixed(d).replace(".", ",") : "–";

  class KmdEasyEnergyCard extends HTMLElement {
    setConfig(config) {
      this._config = {
        language: "da",
        show_sync_bar: true,
        ...config,
      };
      this._lastSig = null;
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      if (typeof this.setAttribute === "function") this.setAttribute("data-kmd-card-version", VER);
      this._render();
    }

    _resolveEntity() {
      const states = this._hass?.states || {};
      if (this._config?.entity && states[this._config.entity]) return states[this._config.entity];
      const all = Object.values(states);
      const isOverview = (s) =>
        typeof s?.entity_id === "string" &&
        s.entity_id.startsWith("sensor.") &&
        Boolean(s.attributes?.utility_id || s.attributes?.portal_url);
      const overview =
        all.find((s) => isOverview(s) && (s.entity_id.endsWith("_overview") || s.entity_id.endsWith("_overblik"))) ||
        all.find(isOverview);
      if (overview) return overview;
      if (states["sensor.kredslob_varme"]) return states["sensor.kredslob_varme"];
      return null;
    }

    // Live MitID challenge (4-digit OTP or both animated QR frames) via the
    // integration's own websocket subscription "kmd_easy_energy/mitid/subscribe".
    // Works for non-admin users (wall tablets) and never touches the event bus /
    // recorder. The bus event kmd_easy_energy_mitid_challenge only carries status.
    _subscribeMitid(hass) {
      if (this._unsubMitid || !hass?.connection?.subscribeMessage) return;
      const onMsg = (d) => {
        d = d || {};
        const st = this._resolveEntity();
        const entryId = st?.attributes?.entry_id;
        const utilId = st?.attributes?.utility_id || this._config?.utility_id;
        if (d.entry_id && entryId && d.entry_id !== entryId) return;
        if (!d.entry_id && d.utility_id && utilId && d.utility_id !== utilId) return;
        const frames = Array.isArray(d.qr_frames) ? d.qr_frames.filter(Boolean) : [];
        const existingImg = this.shadowRoot && this.shadowRoot.getElementById("mitidQrImg");
        if (existingImg && !d.otp_code && frames.length > 0) {
          // Rotate QR frames in place without rebuilding the Shadow DOM or
          // desynchronizing the 1-second frame alternation timer.
          this._mitidOtp = "";
          this._mitidQrFrames = frames;
          this._mitidQr = frames[0];
          this._mitidQrIdx = 0;
          this._prewarmQr(frames);
          existingImg.src = this._qrDataUrl(frames[0]);
          if (this._qrTimer) { clearInterval(this._qrTimer); this._qrTimer = null; }
          this._syncQrAnimation();
          return;
        }
        if (this._qrTimer) { clearInterval(this._qrTimer); this._qrTimer = null; }
        this._mitidOtp = d.otp_code || "";
        this._mitidQrFrames = frames;
        this._mitidQr = frames[0] || "";
        this._mitidQrIdx = 0;
        if (frames.length > 0) this._prewarmQr(frames);
        this._lastSig = null;
        this._render();
        this._syncQrAnimation();
      };
      const p = hass.connection.subscribeMessage(onMsg, { type: "kmd_easy_energy/mitid/subscribe" });
      this._unsubMitid = p;
      if (p && typeof p.catch === "function") {
        p.catch((err) => {
          console.warn("kmd-easy-energy-card: MitID live subscription failed", err);
          this._unsubMitid = null;
        });
      }
    }

    // MitID's QR is animated: two frames (each half of the channel binding) that
    // the MitID app must both see. Alternate them every second by swapping only
    // the <img> src, so the card is not re-rendered on every frame.
    _syncQrAnimation() {
      const frames = this._mitidQrFrames || [];
      if (frames.length < 2) {
        if (this._qrTimer) { clearInterval(this._qrTimer); this._qrTimer = null; }
        return;
      }
      if (this._qrTimer) return;
      this._qrTimer = setInterval(() => {
        const fr = this._mitidQrFrames || [];
        if (fr.length < 2) { clearInterval(this._qrTimer); this._qrTimer = null; return; }
        this._mitidQrIdx = ((this._mitidQrIdx || 0) + 1) % fr.length;
        const img = this.shadowRoot && this.shadowRoot.getElementById("mitidQrImg");
        if (img) img.src = this._qrDataUrl(fr[this._mitidQrIdx]);
      }, 1000);
    }

    _qrDataUrl(svg) {
      return `data:image/svg+xml;utf8,${encodeURIComponent(svg || "")}`;
    }

    _prewarmQr(frames) {
      if (typeof Image !== "function" || !Array.isArray(frames)) return;
      this._qrPrewarm = frames.map((f) => {
        const im = new Image();
        im.src = this._qrDataUrl(f);
        return im;
      });
    }

    _isDesktopWide() {
      return (this.clientWidth || (typeof window !== "undefined" && window.innerWidth) || 1280) >= 768;
    }

    connectedCallback() {
      const checkWidth = () => {
        const wide = this._isDesktopWide();
        if (this._lastDesktopWide !== undefined && wide !== this._lastDesktopWide) {
          this._render();
        }
      };
      if (typeof ResizeObserver === "function" && !this._ro) {
        this._ro = new ResizeObserver(checkWidth);
        this._ro.observe(this);
      } else if (typeof window !== "undefined" && typeof window.addEventListener === "function" && !this._onResize) {
        this._onResize = checkWidth;
        window.addEventListener("resize", this._onResize);
      }
    }

    disconnectedCallback() {
      const unsub = this._unsubMitid;
      this._unsubMitid = null;
      if (this._qrTimer) { clearInterval(this._qrTimer); this._qrTimer = null; }
      if (this._ro) { this._ro.disconnect(); this._ro = null; }
      if (this._onResize && typeof window !== "undefined" && typeof window.removeEventListener === "function") {
        window.removeEventListener("resize", this._onResize);
        this._onResize = null;
      }
      if (typeof unsub === "function") unsub();
      else if (unsub && typeof unsub.then === "function") unsub.then((fn) => fn && fn()).catch(() => {});
    }

    set hass(hass) {
      this._hass = hass;
      this._subscribeMitid(hass);
      const st = this._resolveEntity();
      const statusEnt = this._config?.status_entity;
      const syncSt = statusEnt ? (hass?.states?.[statusEnt]?.state || "") : "";
      const sig = st
        ? `${st.entity_id}|${st.state}|${st.attributes?.updated || ""}|${st.attributes?.hourly?.days_averaged || ""}|${st.attributes?.daily?.latest_complete}|${st.attributes?.last_sync || ""}|${st.attributes?.sync_reminder}|${st.attributes?.days_since_sync}|${st.attributes?.initial_setup_complete}|${st.attributes?.utility_id || ""}|${st.attributes?.entry_id || ""}|${st.attributes?.sync_state || ""}|${st.attributes?.sync_message || ""}|${this._mitidOtp || ""}|${Boolean(this._mitidQr)}|${syncSt}`
        : "none";
      if (sig === this._lastSig) return;
      this._lastSig = sig;
      this._render();
    }

    getCardSize() { return 12; }
    getGridOptions() { return { columns: "full", rows: "auto", min_columns: 6 }; }
    static getConfigElement() { return document.createElement("kmd-easy-energy-card-editor"); }
    static getStubConfig() {
      return { language: "da", show_sync_bar: true };
    }

    _renderMonthlySvg(mCur, mPrev, mTemp, curYr, prevYr, t, mCost = {}) {
      const W = 540, H = 235, pad = { l: 48, r: 38, t: 26, b: 32 };
      const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
      const vals = MONTHS.flatMap((m) => [mCur[m], mPrev[m]]).filter((v) => typeof v === "number");
      const maxKwh = Math.max(3000, ...vals, 1);
      const temps = MONTHS.map((_, i) => mTemp[`${curYr}-${String(i + 1).padStart(2, "0")}`]).filter((v) => typeof v === "number");
      const minT = Math.min(-2, ...temps), maxT = Math.max(20, ...temps);
      const xStep = cw / 12;
      const yKwh = (v) => pad.t + ch - (v / maxKwh) * ch;
      const yTmp = (v) => pad.t + ch - ((v - minT) / Math.max(1, maxT - minT)) * ch;

      let grid = `<text x="${pad.l - 6}" y="13" text-anchor="end" class="ax-unit">kWh</text><text x="${W - pad.r + 6}" y="13" text-anchor="start" class="ax-unit">°C</text>`;
      for (let i = 0; i <= 4; i++) {
        const kv = Math.round((maxKwh / 4) * i);
        const y = yKwh(kv);
        grid += `<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" stroke="rgba(148,163,184,0.22)" stroke-dasharray="3,3"/>`;
        grid += `<text x="${pad.l - 6}" y="${y + 4}" text-anchor="end" class="ax">${fmtInt(kv)}</text>`;
      }
      [0, 10, 20].forEach((tv) => {
        if (tv >= minT && tv <= maxT) {
          const y = yTmp(tv);
          grid += `<text x="${W - pad.r + 6}" y="${y + 4}" text-anchor="start" class="ax-t">${tv}°</text>`;
        }
      });

      let bars = "";
      const pts = [];
      MONTHS.forEach((m, i) => {
        const cx = pad.l + xStep * (i + 0.5);
        const vPrev = mPrev[m];
        const vCur = mCur[m];
        const tCur = mTemp[`${curYr}-${String(i + 1).padStart(2, "0")}`];
        const bw = Math.min(15, xStep * 0.34);

        if (typeof vPrev === "number") {
          const y = yKwh(vPrev);
          bars += `<rect x="${cx - bw - 1}" y="${y}" width="${bw}" height="${Math.max(1, pad.t + ch - y)}" rx="3" fill="rgba(148,163,184,0.45)" tabindex="0" data-tip="${m}: ${prevYr} = ${fmtInt(vPrev)} kWh${typeof vCur === 'number' ? ` · ${curYr} = ${fmtInt(vCur)} kWh` : ''}${typeof tCur === 'number' ? ` · ${t.outdoor} ${fmtDec(tCur)}°C` : ''}"/>`;
        }
        if (typeof vCur === "number") {
          const y = yKwh(vCur);
          const costTip = typeof mCost[m] === "number" ? ` · ~${fmtInt(mCost[m])} kr.` : "";
          bars += `<rect x="${cx + 1}" y="${y}" width="${bw}" height="${Math.max(1, pad.t + ch - y)}" rx="3" fill="url(#gHeat)" tabindex="0" data-tip="${m}: ${curYr} = ${fmtInt(vCur)} kWh${costTip}${typeof vPrev === 'number' ? ` (${prevYr}: ${fmtInt(vPrev)} kWh)` : ''}${typeof tCur === 'number' ? ` · ${t.outdoor} ${fmtDec(tCur)}°C` : ''}"/>`;
        }
        if (typeof tCur === "number") {
          pts.push([cx, yTmp(tCur), `${m} ${t.outdoor.toLowerCase()}: ${fmtDec(tCur)} °C`]);
        }
        bars += `<text x="${cx}" y="${H - 8}" text-anchor="middle" class="ax">${m}</text>`;
      });

      let line = "";
      if (pts.length > 1) {
        const d = pts.map((p, idx) => `${idx === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
        line = `<path d="${d}" fill="none" stroke="#38bdf8" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>`;
        pts.forEach(([x, y, tip]) => {
          line += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.6" fill="#0ea5e9" stroke="var(--card-background-color, #fff)" stroke-width="1.4" tabindex="0" data-tip="${esc(tip)}"/>`;
        });
      }
      return `<svg viewBox="0 0 ${W} ${H}" class="svg"><defs><linearGradient id="gHeat" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#f97316"/><stop offset="100%" stop-color="#ef4444"/></linearGradient></defs>${grid}${bars}${line}</svg>`;
    }

    _renderReturnTempSvg(rtMonthly, bonusT, penaltyT, curYr, expMonthly = {}, allowBonus = true) {
      const W = 540, H = 225, pad = { l: 42, r: 14, t: 28, b: 32 };
      const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
      const expVals = MONTHS.map((m) => expMonthly?.[m]).filter((v) => typeof v === "number" && Number.isFinite(v) && v > 0);
      const useExpCurve = expVals.length >= 2;
      const hasAnyExp = expVals.length >= 1;
      const barVals = MONTHS.map((m) => rtMonthly?.[m]).filter((v) => typeof v === "number" && Number.isFinite(v) && v > 0);
      const allVals = [...barVals, ...expVals, ...(allowBonus ? [bonusT] : []), penaltyT].filter((v) => Number.isFinite(v) && v > 0);
      const minY = Math.min(20, allVals.length ? Math.floor(Math.min(...allVals) - 2) : 20);
      const maxY = Math.max(44, allVals.length ? Math.ceil(Math.max(...allVals) + 3) : 44);
      const yPos = (v) => pad.t + ch - ((v - minY) / (maxY - minY)) * ch;
      const xStep = cw / 12;

      let grid = "";
      const refLines = useExpCurve
        ? [25, 35]
        : [25, ...(allowBonus ? [bonusT] : []), 35, penaltyT].filter((v, i, a) => Number.isFinite(v) && v > 0 && a.indexOf(v) === i);
      refLines.forEach((tv) => {
        const y = yPos(tv);
        const isBonusLine = !useExpCurve && allowBonus && tv === bonusT;
        const isPenaltyLine = !useExpCurve && tv === penaltyT;
        const col = isBonusLine ? "#22c55e" : (isPenaltyLine ? "#ef4444" : "rgba(148,163,184,0.22)");
        const dash = (isBonusLine || isPenaltyLine) ? "5,4" : "3,3";
        const sw = (isBonusLine || isPenaltyLine) ? "1.6" : "1";
        const cls = isBonusLine ? "ax-bonus" : (isPenaltyLine ? "ax-penalty" : "ax");
        grid += `<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" stroke="${col}" stroke-width="${sw}" stroke-dasharray="${dash}"/>`;
        grid += `<text x="${pad.l - 6}" y="${y + 4}" text-anchor="end" class="${cls}">${tv}°</text>`;
      });

      let bars = "";
      const expPts = [];
      MONTHS.forEach((m, i) => {
        const cx = pad.l + xStep * (i + 0.5);
        const v = rtMonthly[m];
        const mExp = (hasAnyExp && typeof expMonthly?.[m] === "number" && Number.isFinite(expMonthly[m]) && expMonthly[m] > 0)
          ? expMonthly[m]
          : null;
        const effB = mExp !== null ? mExp : bonusT;
        const effP = mExp !== null ? mExp : penaltyT;
        if (typeof v === "number") {
          const y = yPos(Math.min(maxY, Math.max(minY, v)));
          const col = !allowBonus
            ? (v <= effP ? "#22c55e" : "#ef4444")
            : (v < effB ? "#22c55e" : (v <= effP ? "#f59e0b" : "#ef4444"));
          const bw = Math.min(24, xStep * 0.58);
          const tip = mExp !== null
            ? (!allowBonus
              ? `${m} ${curYr}: ${fmtDec(v)} °C · krav ≤${fmtDec(mExp)} °C (${v <= effP ? "OK — intet gebyr" : "Gebyr!"})`
              : `${m} ${curYr}: ${fmtDec(v)} °C · krav ${fmtDec(mExp)} °C (${v < effB ? "Bonus!" : v <= effP ? "På krav" : "Gebyr!"})`)
            : (!allowBonus
              ? `${m} ${curYr}: ${fmtDec(v)} °C · krav ≤${fmtDec(penaltyT)} °C (${v <= penaltyT ? "OK — intet gebyr" : "Gebyr!"})`
              : `${m} ${curYr}: ${fmtDec(v)} °C (${v < bonusT ? "Bonus!" : v <= penaltyT ? "Neutral" : "Gebyr!"})`);
          bars += `<rect x="${cx - bw / 2}" y="${y}" width="${bw}" height="${Math.max(2, pad.t + ch - y)}" rx="5" fill="${col}" fill-opacity="0.88" tabindex="0" data-tip="${esc(tip)}"/>`;
          bars += `<text x="${cx}" y="${y - 7}" text-anchor="middle" class="val val-sm">${fmtDec(v)}</text>`;
        }
        if (mExp !== null) {
          expPts.push([cx, yPos(Math.min(maxY, Math.max(minY, mExp))), m, mExp]);
        }
        bars += `<text x="${cx}" y="${H - 8}" text-anchor="middle" class="ax">${m}</text>`;
      });
      let expLine = "";
      if (expPts.length >= 2) {
        const d = expPts.map((p, idx) => `${idx === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
        expLine = `<path d="${d}" fill="none" stroke="#38bdf8" stroke-width="2.2" stroke-dasharray="5,3" stroke-linecap="round" stroke-linejoin="round" data-role="expected-return-curve"/>`;
      }
      if (expPts.length >= 1) {
        expPts.forEach(([x, y, m, mExp]) => {
          expLine += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.6" fill="#0ea5e9" stroke="var(--card-background-color, #fff)" stroke-width="1.2" tabindex="0" data-tip="Forventet retur ${m} ${curYr}: ${fmtDec(mExp)} °C"/>`;
        });
      }
      return `<svg viewBox="0 0 ${W} ${H}" class="svg">${grid}${bars}${expLine}</svg>`;
    }

    _renderHourlyAvgSvg(hourly, bonusT, peakInfo) {
      const kwh = Array.isArray(hourly?.kwh) ? hourly.kwh : [];
      const rt = Array.isArray(hourly?.ret_temp) ? hourly.ret_temp : [];
      const W = 540, H = 230, pad = { l: 40, r: 42, t: 28, b: 32 };
      const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
      const validK = kwh.filter((v) => typeof v === "number" && Number.isFinite(v));
      const rawMaxK = validK.length ? Math.max(...validK) * 1.18 : 3.2;
      const maxK = Math.max(rawMaxK < 1.5 ? 1.5 : 3.2, rawMaxK);
      const validT = rt.filter((v) => typeof v === "number" && Number.isFinite(v));
      const minT = Math.min(25, ...validT, bonusT - 2);
      const maxT = Math.max(36, ...validT, bonusT + 4);
      const xStep = cw / 24;
      const yK = (v) => pad.t + ch - (v / maxK) * ch;
      const yT = (t) => pad.t + ch - ((t - minT) / Math.max(1, maxT - minT)) * ch;

      let grid = `<text x="${pad.l - 6}" y="13" text-anchor="end" class="ax-unit">kWh/t</text><text x="${W - pad.r + 6}" y="13" text-anchor="start" class="ax-unit">°C</text>`;
      const kStep = maxK <= 1.8 ? 0.5 : (maxK <= 5 ? 1 : niceStep(maxK, 4));
      for (let kv = kStep; kv <= maxK + 1e-6; kv += kStep) {
        const y = yK(kv);
        if (y >= pad.t - 2) {
          grid += `<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" stroke="rgba(148,163,184,0.20)" stroke-dasharray="3,3"/>`;
          grid += `<text x="${pad.l - 6}" y="${y + 4}" text-anchor="end" class="ax">${kStep < 1 ? fmtDec(kv, 1) : Math.round(kv)}</text>`;
        }
      }
      if (bonusT >= minT && bonusT <= maxT) {
        grid += `<line x1="${pad.l}" y1="${yT(bonusT)}" x2="${W - pad.r}" y2="${yT(bonusT)}" stroke="rgba(34,197,94,0.65)" stroke-dasharray="4,4"/>`;
        grid += `<text x="${W - pad.r + 6}" y="${yT(bonusT) + 4}" class="ax-bonus">${bonusT}°</text>`;
      }
      [Math.round(minT), Math.round(maxT)].forEach((tv) => {
        if (Math.abs(tv - bonusT) >= 3) {
          grid += `<text x="${W - pad.r + 6}" y="${yT(tv) + 4}" class="ax-t">${tv}°</text>`;
        }
      });

      const info = peakInfo || identifyPeakHours(kwh);
      let bars = "";
      const pts = [];
      for (let h = 0; h < 24; h++) {
        const cx = pad.l + xStep * (h + 0.5);
        const kv = kwh[h];
        const tv = rt[h];
        if (typeof kv === "number") {
          const y = yK(kv);
          const isPeak = info.peaks.has(h);
          const bw = Math.min(15, xStep * 0.64);
          bars += `<rect x="${cx - bw / 2}" y="${y}" width="${bw}" height="${Math.max(2, pad.t + ch - y)}" rx="3.5" fill="${isPeak ? '#ec4899' : '#f59e0b'}" fill-opacity="${isPeak ? '0.94' : '0.72'}" tabindex="0" data-tip="Kl. ${String(h).padStart(2, '0')}:00 snit: ${fmtDec(kv, 2)} kWh/t${isPeak ? ' (Spidstime)' : ''}${typeof tv === 'number' ? ` · Retur ${fmtDec(tv)} °C` : ''}"/>`;
          if (h === info.maxIdx && info.peaks.has(h)) {
            bars += `<text x="${cx}" y="${Math.max(pad.t - 4, y - 6)}" text-anchor="middle" class="val">${fmtDec(kv, 2)}</text>`;
          }
        }
        if (typeof tv === "number") {
          pts.push([cx, yT(Math.min(maxT, Math.max(minT, tv))), `Kl. ${String(h).padStart(2, '0')}:00 snit retur: ${fmtDec(tv)} °C`]);
        }
        if (h % 3 === 0) bars += `<text x="${cx}" y="${H - 8}" text-anchor="middle" class="ax">${String(h).padStart(2, "0")}</text>`;
      }

      let line = "";
      if (pts.length > 1) {
        const d = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
        line = `<path d="${d}" fill="none" stroke="#38bdf8" stroke-width="2.4" stroke-linejoin="round"/>`;
        pts.forEach(([x, y, tip]) => {
          line += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.4" fill="#0ea5e9" stroke="var(--card-background-color, #fff)" stroke-width="1" tabindex="0" data-tip="${esc(tip)}"/>`;
        });
      }
      return `<svg viewBox="0 0 ${W} ${H}" class="svg">${grid}${bars}${line}</svg>`;
    }

    _renderMtdVsYtdSvg(ann, mPrev, dy, curYr, prevYr) {
      const days = dy?.days || {};
      const entries = Object.keys(days).map((k) => [parseInt(k, 10), days[k]]).sort((a, b) => a[0] - b[0]);
      const hasTrailingPartial = entries.length > 2 && (dy?.latest_complete === false || entries[entries.length - 1][1] < 10);
      const trailingPartialVal = hasTrailingPartial ? Number(entries[entries.length - 1][1] || 0) : 0;
      const cleanDays = hasTrailingPartial ? entries.slice(0, -1) : entries;
      const mtdAvg = cleanDays.length ? cleanDays.reduce((s, x) => s + x[1], 0) / cleanDays.length : Number(dy?.gennemsnit || 0);

      const now = new Date();
      const latestDayNum = cleanDays.length ? cleanDays[cleanDays.length - 1][0] : now.getDate();
      let mIdx = now.getMonth();
      if (typeof dy?.latest_date === "string" && dy.latest_date.startsWith(`${curYr}-`)) {
        const parsedMo = parseInt(dy.latest_date.slice(5, 7), 10);
        if (parsedMo >= 1 && parsedMo <= 12) mIdx = parsedMo - 1;
      }
      let daysElapsed = latestDayNum;
      for (let i = 0; i < mIdx; i++) daysElapsed += daysInMonth(i, curYr);
      const ytdTotal = Math.max(0, Number(ann[String(curYr)] || 0) - trailingPartialVal);
      const ytdAvg = daysElapsed > 0 ? ytdTotal / daysElapsed : 0;

      const curMonthName = MONTHS[mIdx] || "Nov";
      const prevYearSameMonthTotal = Number(mPrev[curMonthName] || 0);
      const prevYearSameMonthAvg = prevYearSameMonthTotal > 0 ? prevYearSameMonthTotal / daysInMonth(mIdx, prevYr) : 0;
      const prevYrDays = isLeapYear(prevYr) ? 366 : 365;
      const prevYrAvg = Number(ann[String(prevYr)] || 0) / prevYrDays;

      const barsData = [
        { lbl: `${curMonthName} MTD`, sub: `${cleanDays.length} dage`, val: mtdAvg, col: "#f97316" },
        { lbl: `${curMonthName} ${prevYr}`, sub: `${fmtInt(prevYearSameMonthTotal)} kWh`, val: prevYearSameMonthAvg, col: "#94a3b8" },
        { lbl: `${curYr} ÅTD snit`, sub: `${daysElapsed} dage`, val: ytdAvg, col: "#38bdf8" },
        { lbl: `${prevYr} årssnit`, sub: `${prevYrDays} dage`, val: prevYrAvg, col: "#64748b" },
      ].filter((b) => b.val > 0);

      const W = 540, H = 235, pad = { l: 44, r: 16, t: 30, b: 48 };
      const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
      const maxV = Math.max(60, ...barsData.map((b) => b.val * 1.18));
      const yPos = (v) => pad.t + ch - (v / maxV) * ch;
      const xStep = cw / Math.max(1, barsData.length);

      let grid = `<text x="${pad.l - 6}" y="13" text-anchor="end" class="ax-unit">kWh/d</text>`;
      const step = niceStep(maxV, 3);
      for (let kv = step; kv <= maxV; kv += step) {
        const y = yPos(kv);
        grid += `<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" stroke="rgba(148,163,184,0.20)" stroke-dasharray="3,3"/>`;
        grid += `<text x="${pad.l - 6}" y="${y + 4}" text-anchor="end" class="ax">${Math.round(kv)}</text>`;
      }

      let bars = "";
      barsData.forEach((b, i) => {
        const cx = pad.l + xStep * (i + 0.5);
        const y = yPos(b.val);
        const bw = Math.min(54, xStep * 0.52);
        bars += `<rect x="${cx - bw / 2}" y="${y}" width="${bw}" height="${Math.max(2, pad.t + ch - y)}" rx="7" fill="${b.col}" fill-opacity="0.88" tabindex="0" data-tip="${esc(`${b.lbl}: ${fmtDec(b.val)} kWh/dag (${b.sub})`)}"/>`;
        bars += `<text x="${cx}" y="${y - 8}" text-anchor="middle" class="val val-lg">${fmtDec(b.val)} kWh/d</text>`;
        bars += `<text x="${cx}" y="${H - 22}" text-anchor="middle" class="ax">${esc(b.lbl)}</text>`;
        bars += `<text x="${cx}" y="${H - 6}" text-anchor="middle" class="ax-sub">${esc(b.sub)}</text>`;
      });
      return `<svg viewBox="0 0 ${W} ${H}" class="svg">${grid}${bars}</svg>`;
    }

    _renderDailySvg(daily, dailyTemp, t, wide = false) {
      const days = daily?.days || {};
      const entries = Object.keys(days).map((k) => [parseInt(k, 10), days[k]]).sort((a, b) => a[0] - b[0]);
      const clean = entries.filter(([, v], idx) => !(idx === entries.length - 1 && entries.length > 2 && (daily?.latest_complete === false || v < 10)));
      if (clean.length === 0) return `<div class="empty">${esc(t.no_daily)}</div>`;

      const ymPrefix = (daily?.latest_date || new Date().toISOString().slice(0, 7)).slice(0, 7);
      const W = wide ? 960 : 540, H = 220, pad = { l: 42, r: 40, t: 26, b: 32 };
      const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
      const topK = Math.max(70, ...clean.map((x) => x[1] * 1.08));
      const tVals = clean.map(([d]) => dailyTemp[`${ymPrefix}-${String(d).padStart(2, "0")}`]).filter((v) => typeof v === "number");
      const minT = Math.floor(Math.min(0, ...tVals));
      const maxT = Math.ceil(Math.max(12, ...tVals));
      const xStep = cw / clean.length;
      const yK = (v) => pad.t + ch - (v / topK) * ch;
      const yT = (v) => pad.t + ch - ((v - minT) / Math.max(1, maxT - minT)) * ch;

      let grid = `<text x="${pad.l - 6}" y="13" text-anchor="end" class="ax-unit">kWh</text><text x="${W - pad.r + 6}" y="13" text-anchor="start" class="ax-unit">°C</text>`;
      const kStep = niceStep(topK, 3);
      for (let kv = kStep; kv <= topK; kv += kStep) {
        const y = yK(kv);
        grid += `<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" stroke="rgba(148,163,184,0.20)" stroke-dasharray="3,3"/>`;
        grid += `<text x="${pad.l - 6}" y="${y + 4}" text-anchor="end" class="ax">${Math.round(kv)}</text>`;
      }
      if (tVals.length > 0) {
        const midT = Math.round((minT + maxT) / 2);
        [minT, midT, maxT].filter((v, i, a) => a.indexOf(v) === i).forEach((tv) => {
          const y = yT(tv);
          grid += `<text x="${W - pad.r + 6}" y="${y + 4}" text-anchor="start" class="ax-t">${tv}°</text>`;
        });
      }

      const labelStep = (!wide && clean.length > 15) ? 2 : (clean.length > 31 ? 2 : 1);
      let bars = "";
      const pts = [];
      clean.forEach(([d, v], idx) => {
        const cx = pad.l + xStep * (idx + 0.5);
        const y = yK(v);
        const bw = Math.min(wide ? 22 : 20, xStep * 0.64);
        const dt = dailyTemp[`${ymPrefix}-${String(d).padStart(2, "0")}`];
        bars += `<rect x="${cx - bw / 2}" y="${y}" width="${bw}" height="${Math.max(2, pad.t + ch - y)}" rx="3.5" fill="url(#gDay)" tabindex="0" data-tip="${esc(`${d}.: ${v} kWh${typeof dt === 'number' ? ` · ${t.outdoor} ${fmtDec(dt)} °C` : ''}`)}"/>`;
        if (idx % labelStep === 0 || idx === clean.length - 1 && (clean.length - 1) % labelStep === 0) {
          bars += `<text x="${cx}" y="${H - 8}" text-anchor="middle" class="ax">${d}.</text>`;
        }
        if (typeof dt === "number") pts.push([cx, yT(dt), `${d}. ${t.outdoor.toLowerCase()}: ${fmtDec(dt)} °C`]);
      });

      let line = "";
      if (pts.length > 1) {
        const path = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
        line = `<path d="${path}" fill="none" stroke="#38bdf8" stroke-width="2.3"/>`;
        pts.forEach(([x, y, tip]) => {
          line += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5" fill="#0ea5e9" stroke="var(--card-background-color, #fff)" stroke-width="1" tabindex="0" data-tip="${esc(tip)}"/>`;
        });
      }
      return `<svg viewBox="0 0 ${W} ${H}" class="svg"><defs><linearGradient id="gDay" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#fb923c"/><stop offset="100%" stop-color="#f59e0b"/></linearGradient></defs>${grid}${bars}${line}</svg>`;
    }

    _render() {
      if (!this.shadowRoot) return;
      const cfg = this._config || {};
      const lang = cfg.language === "en" ? "en" : "da";
      const t = I18N[lang];
      const st = this._resolveEntity();
      const a = st?.attributes || {};
      const now = new Date();
      const curYr = now.getFullYear();
      const prevYr = curYr - 1;
      const bonusT = Number(cfg.bonus_temp ?? a.bonus_temp ?? 30);
      const penaltyT = Number(cfg.penalty_temp ?? a.penalty_temp ?? 40);
      const tariffObj = a.tariff || {};
      const allowBonus = (cfg.bonus_temp != null && Number(cfg.bonus_temp) > 0)
        ? true
        : (tariffObj.motivation_bonus !== false && bonusT > 0);
      const hasDynamicCurve = Array.isArray(tariffObj.expected_return_by_forward_temp) && tariffObj.expected_return_by_forward_temp.length >= 2;
      const fwdTemp = typeof a.forward_temp === "number" && a.forward_temp > 0 ? a.forward_temp : null;
      const fwdSrc = a.forward_temp_source || tariffObj.forward_temp_source || null;
      const curPrice = a.energy_price_dkk_per_kwh ?? tariffObj.price_dkk_per_kwh ?? "";
      const curMotivPct = tariffObj.motivation_pct_per_k ?? "";
      const curFixedM2 = tariffObj.fixed_fee_dkk_per_m2_year ?? "";
      const curAreaM2 = tariffObj.heated_area_m2 ?? "";
      const curFixedYear = tariffObj.fixed_fee_dkk_per_year ?? "";
      const efExpectedRt = typeof a.expected_return_temp === "number" ? a.expected_return_temp : null;
      const singleReturnTarget = !allowBonus || Math.abs(bonusT - penaltyT) < 0.05;

      const ann = a.annual || {};
      const mon = a.monthly || {};
      const mCur = mon[String(curYr)] || {};
      const mPrev = mon[String(prevYr)] || {};
      const dy = a.daily || {};
      const hr = a.hourly || {};
      const rt = a.return_temp || {};
      const rtA = rt.annual || {};
      const rtM = rt[`monthly_${curYr}`] || rt.monthly_2026 || {};
      const rtExpM = (cfg.bonus_temp == null && cfg.penalty_temp == null && a.expected_return_auto !== false)
        ? (rt[`expected_monthly_${curYr}`] || rt.expected_monthly_2026 || {})
        : {};
      const expMList = MONTHS.map((m) => rtExpM[m]).filter((v) => typeof v === "number" && v > 0);
      const hasExpMonthly = expMList.length > 0;
      const expMin = hasExpMonthly ? Math.min(...expMList) : null;
      const expMax = hasExpMonthly ? Math.max(...expMList) : null;
      const expRangeTxt = hasExpMonthly && Math.abs(expMax - expMin) >= 0.5
        ? `${fmtDec(expMin, 0)}–${fmtDec(expMax, 0)}°`
        : `${allowBonus ? bonusT : penaltyT}°`;
      const wx = a.weather || {};
      const ins = a.insights || {};
      const fc = a.forecast || {};
      const bl = a.billing || {};
      const costEst = a.cost_estimate || {};

      // Capability-driven rendering: the integration reports which data the
      // backend actually delivered. Sections without data are hidden (no empty
      // charts, no "–" tiles). Old integrations without the attribute: show all.
      const capList = Array.isArray(a.capabilities) ? a.capabilities : null;
      const has = (c) => (capList ? capList.includes(c) : true);
      const backend = a.backend || "kmd";
      const hasMitid = capList ? capList.includes("mitid") : backend === "kmd";
      const dataSource = a.data_source || ({ eforsyning: "E|Forsyning", wattson: "Watts On" }[backend] || "KMD Easy Energy");
      const loginHow = backend === "wattson"
        ? "Login med din Watts On-konto (browser-login, din adgangskode gemmes ikke)"
        : "Login med forbrugernummer og webpinkode";
      const yCur = Number(ann[String(curYr)] ?? st?.state ?? 0);
      const yPrev = Number(ann[String(prevYr)] ?? 0);
      const rtCur = Number(rtA[String(curYr)] ?? rtA["2026"] ?? 0);
      const expK = Number(fc.expected_kwh ?? 0);
      const budK = Number(fc.budget_kwh ?? 0);
      const fcPct = budK > 0 ? Math.round(((expK - budK) / budK) * 100) : 0;
      const hddMap = ins.kwh_per_hdd || {};
      const hrArr = Array.isArray(hr.kwh) ? hr.kwh : [];
      const peakInfo = identifyPeakHours(hrArr);
      const peakHourVal = peakInfo.maxVal || (hrArr.length ? Math.max(...hrArr) : 0);
      const peakHourIdx = peakInfo.maxIdx || (hrArr.length ? hrArr.indexOf(peakHourVal) : 0);
      const minHourVal = peakInfo.minPos || (hrArr.length ? Math.min(...hrArr) : 0);
      const peakLegendTxt = peakInfo.peaks.size > 1
        ? `Peak ${String(peakHourIdx).padStart(2, "0")}:00 (${fmtDec(peakHourVal, 2)} kWh/t) · ${peakInfo.peaks.size} ${lang === "en" ? "peak hrs" : "spidstimer"}`
        : peakInfo.peaks.size === 1
          ? `Peak ${String(peakHourIdx).padStart(2, "0")}:00 (${fmtDec(peakHourVal, 2)} kWh/t)`
          : `${lang === "en" ? "No sharp peak" : "Ingen markant spidstime"} (maks ${fmtDec(peakHourVal, 2)} kWh/t)`;
      const peakOtherList = peakInfo.peakList.filter((h) => h !== peakHourIdx).map((h) => `kl. ${String(h).padStart(2, "0")}:00`);
      const peakInsightSub = peakOtherList.length ? ` (samt ${peakOtherList.join(", ")})` : "";
      const baseDayKwh = Number(ins.baseload_kwh_mo ?? 0) / 30;
      const rtDist = rtCur > 0 ? rtCur - bonusT : 0;
      const hddEntries = Object.entries(hddMap);
      const hddSummary = hddEntries.length >= 2
        ? `${hddEntries[hddEntries.length - 1][0]} ligger på ${fmtDec(hddEntries[hddEntries.length - 1][1], 2)} kWh/HDD mod ${fmtDec(hddEntries[hddEntries.length - 2][1], 2)} i ${hddEntries[hddEntries.length - 2][0]}:`
        : "Vejrkorrigeret rumvarme-forbrug pr. graddag:";

      // Session-based sync: "Sidst synkroniseret" = last MitID sync (no background polling).
      const lastSyncRaw = a.last_sync || a.updated || "";
      const uDate = lastSyncRaw ? new Date(lastSyncRaw) : null;
      const validU = uDate && !Number.isNaN(uDate.getTime());
      const isToday = validU && uDate.toDateString() === now.toDateString();
      const hhmm = validU ? `${String(uDate.getHours()).padStart(2, "0")}:${String(uDate.getMinutes()).padStart(2, "0")}` : "";
      const retrievedLbl = isToday
        ? `${t.last_sync} i dag ${hhmm}`
        : validU
          ? `${t.last_sync} ${uDate.getDate()}. ${(MONTHS[uDate.getMonth()] || "").toLowerCase()} ${hhmm}`
          : t.never_synced;
      // Soft weekend reminder (computed by the integration; visual only, no push).
      const syncReminder = Boolean(a.sync_reminder);
      const syncReminderMsg = String(a.sync_reminder_message || "");
      const dayKeys = Object.keys(dy.days || {}).map((k) => parseInt(k, 10)).filter((n) => !Number.isNaN(n));
      const maxDay = dayKeys.length ? Math.max(...dayKeys) : null;
      const moLbl = (dy.month || "").split(" ")[0].slice(0, 3).toLowerCase();
      const isPartial = maxDay !== null && (
        dy.latest_complete === false ||
        (dy.latest_complete === undefined && Number(dy.gennemsnit) > 0 && Number(dy.days[String(maxDay)]) < Number(dy.gennemsnit) * 0.35)
      );
      const freshText = retrievedLbl + (maxDay !== null ? ` · Data t.o.m. ${maxDay}. ${moLbl}${isPartial ? " (delvis)" : ""}` : "");

      const normPortal = (u) => String(u || "").trim().replace(/\/+$/, "").toLowerCase();
      const rawUtilId = this._selectedUtilId || cfg.utility_id || a.utility_id || "kredslob";
      const rawPortalUrl = cfg.portal_url || a.portal_url || "";
      const portalMatch = (rawUtilId === "eforsyning-custom" || rawUtilId === "custom") && rawPortalUrl
        ? UTILITIES.find((u) => u.url && normPortal(u.url) === normPortal(rawPortalUrl))
        : null;
      const activeUtilId = portalMatch ? portalMatch.id : rawUtilId;
      const activeUtil = UTILITIES.find((u) => u.id === activeUtilId)
        || (a.utility ? { id: activeUtilId, name: a.utility, city: a.location || "", url: a.portal_url || "", status: a.utility_status || "pending_test", backend } : UTILITIES[0]);
      const activePortalUrl = cfg.portal_url || a.portal_url || activeUtil.url;
      const locName = cfg.location || a.location || activeUtil.city || "Lokal";
      const utilStatus = portalMatch
        ? portalMatch.status
        : (activeUtil?.id === activeUtilId && activeUtil?.status === "confirmed"
          ? "confirmed"
          : (a.utility_status || activeUtil.status));
      const statusBadge = utilStatus === "confirmed" ? t.confirmed : t.pending;

      // The MitID wizard only lists KMD utilities (E|Forsyning / Watts On are set up in HA's config flow).
      const kmdUtils = UTILITIES.filter((u) => (u.backend || "kmd") === "kmd");
      const confirmedOpts = kmdUtils.filter((u) => u.status === "confirmed")
        .map((u) => `<option value="${u.id}" ${u.id === activeUtilId ? "selected" : ""}>✅ ${esc(u.name)} (${esc(u.city)})</option>`).join("");
      const pendingOpts = kmdUtils.filter((u) => u.status !== "confirmed")
        .map((u) => `<option value="${u.id}" ${u.id === activeUtilId ? "selected" : ""}>🧪 ${esc(u.name)} (${esc(u.city)})</option>`).join("");

      const statusEnt = cfg.status_entity;
      const legacySyncMsg = statusEnt ? this._hass?.states?.[statusEnt]?.state : "";
      const nativeSyncMsg = a.sync_message || "";
      const syncMsg = nativeSyncMsg || (legacySyncMsg && legacySyncMsg !== "unknown" && legacySyncMsg !== "unavailable" ? legacySyncMsg : "");
      const hasSyncMsg = Boolean(syncMsg);
      const otpCode = this._mitidOtp || "";
      const qrSvg = this._mitidQr || "";
      const hasMitidUser = Boolean(a.has_mitid_username);
      const mitidMasked = a.mitid_username_masked || "";
      const notifySvc = String(this._wizNotify ?? (a.notify_service || "")).replace(/^notify\./, "").trim();
      const rawNotify = Object.keys(this._hass?.services?.notify || {})
        .filter((s) => !["persistent_notification", "send_message", "notify"].includes(s));
      const mobileNotify = rawNotify.filter((s) => s.startsWith("mobile_app_")).sort();
      const otherNotify = rawNotify.filter((s) => !s.startsWith("mobile_app_")).sort();
      const allNotifyIds = [...mobileNotify, ...otherNotify];
      const isCustomNotify = Boolean(this._wizNotifyCustom) || (Boolean(notifySvc) && !allNotifyIds.includes(notifySvc));
      const fmtMobileLabel = (s) => `📱 ${s.slice("mobile_app_".length).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} (${s})`;
      const mobileNotifyOpts = mobileNotify
        .map((s) => `<option value="${esc(s)}" ${!isCustomNotify && s === notifySvc ? "selected" : ""}>${esc(fmtMobileLabel(s))}</option>`).join("");
      const otherNotifyOpts = otherNotify
        .map((s) => `<option value="${esc(s)}" ${!isCustomNotify && s === notifySvc ? "selected" : ""}>🔔 ${esc(s)}</option>`).join("");
      const notifySelectHtml = `
        <select id="notifySel" aria-label="Select notify service">
          <option value="" ${!isCustomNotify && !notifySvc ? "selected" : ""}>— Ingen mobil-push (kun notifikation i HA) —</option>
          ${mobileNotifyOpts ? `<optgroup label="📱 Telefoner (Home Assistant App)">${mobileNotifyOpts}</optgroup>` : ""}
          ${otherNotifyOpts ? `<optgroup label="🔔 Øvrige notify-tjenester">${otherNotifyOpts}</optgroup>` : ""}
          <option value="__custom__" ${isCustomNotify ? "selected" : ""}>✏️ Andet (indtast manuelt)…</option>
        </select>
        ${isCustomNotify ? `<input id="notifyInput" aria-label="Brugerdefineret notify-tjeneste" value="${esc(notifySvc)}" placeholder="f.eks. mobile_app_min_telefon" style="margin-top:6px" />` : ""}`;
      const hasData = Boolean(
        st && (Object.keys(ann).length > 0 || Object.keys(mon).length > 0 || Object.keys(dy.days || {}).length > 0)
      );
      const isAdmin = this._hass?.user?.is_admin !== false;
      const isInitialSetup = !hasData || a.initial_setup_complete === false;
      const showOnboarding = isInitialSetup || (isAdmin && Boolean(this._setupOpen));
      const chartCount = [has("monthly"), has("temperatures"), has("hourly"), has("daily"), has("daily")].filter(Boolean).length;
      const isDesktopWide = this._isDesktopWide();
      this._lastDesktopWide = isDesktopWide;
      const wideDaily = chartCount % 2 === 1 && isDesktopWide;
      const wizPortalUrl = this._wizPortalUrl ?? activePortalUrl;
      const wizLocation = this._wizLocation ?? locName;
      const wizBonus = this._wizBonus ?? bonusT;
      const wizPenalty = this._wizPenalty ?? penaltyT;
      const wizPrice = this._wizPrice ?? (curPrice !== "" && curPrice !== null ? curPrice : "");
      const wizMotivPct = this._wizMotivPct ?? (curMotivPct !== "" && curMotivPct !== null ? curMotivPct : "");
      const wizFixedM2 = this._wizFixedM2 ?? (curFixedM2 !== "" && curFixedM2 !== null ? curFixedM2 : "");
      const wizAreaM2 = this._wizAreaM2 ?? (curAreaM2 !== "" && curAreaM2 !== null ? curAreaM2 : "");
      const wizFixedYear = this._wizFixedYear ?? (curFixedYear !== "" && curFixedYear !== null ? curFixedYear : "");
      const wizEfPrice = this._wizEfPrice ?? wizPrice;
      const wizEfBonus = this._wizEfBonus ?? (allowBonus ? (efExpectedRt !== null ? efExpectedRt : bonusT) : "");
      const wizEfPenalty = this._wizEfPenalty ?? (allowBonus && singleReturnTarget ? "" : penaltyT);
      const wizEfMotivPct = this._wizEfMotivPct ?? wizMotivPct;
      const wizEfForward = this._wizEfForward ?? (fwdSrc === "manual" && fwdTemp !== null ? fwdTemp : "");
      const wizEfFixedM2 = this._wizEfFixedM2 ?? wizFixedM2;
      const wizEfAreaM2 = this._wizEfAreaM2 ?? wizAreaM2;
      const wizEfFixedYear = this._wizEfFixedYear ?? wizFixedYear;
      const mitidLiveBox = !hasMitid ? "" : otpCode
        ? `<div class="mitid-box otp" role="region" aria-live="polite"><div>🔑 Indtast denne 4-cifrede engangskode i MitID-appen:</div><div class="otp-digits">${esc(otpCode.split("").join(" "))}</div></div>`
        : (qrSvg ? `<div class="mitid-box qr" role="region" aria-live="polite"><div>📲 Scan QR-koden med MitID-appen på din telefon:</div><div class="qr-wrap"><img id="mitidQrImg" src="${esc(this._qrDataUrl((this._mitidQrFrames || [])[this._mitidQrIdx || 0] || qrSvg))}" alt="MitID QR-kode" /></div><div class="qr-hint">Koden skifter hvert sekund — hold telefonen roligt foran skærmen. Står kortet på samme telefon som MitID-appen, kan QR-koden ikke scannes — slå i stedet engangskoder til i MitID-appen (Menu → Godkend med QR- eller engangskoder → Engangskoder).</div></div>` : "");

      // Dynamic Mushroom-style banner state
      let bannerIcon = isToday ? "✓" : "↻";
      let bannerTone = isToday ? "ok" : "orange";
      let bannerTitle = isToday
        ? `${activeUtil.name} Fjernvarme · Synkroniseret i dag`
        : (hasMitid ? "Synkroniser fjernvarme (MitID)" : "Synkroniser fjernvarme");
      let bannerSub = `${freshText} · Tryk for at synkronisere`;
      if (hasSyncMsg) {
        if (syncMsg.startsWith("Fejl")) {
          bannerIcon = "!";
          bannerTone = "red";
          bannerTitle = "Fjernvarme sync fejlede";
          bannerSub = syncMsg;
        } else if (hasMitid && syncMsg.includes("MitID")) {
          bannerIcon = "🔑";
          bannerTone = "blue";
          bannerTitle = "Venter på MitID-godkendelse…";
          bannerSub = syncMsg;
        } else {
          bannerIcon = "⟳";
          bannerTone = "amber";
          bannerTitle = "Synkroniserer fjernvarme…";
          bannerSub = syncMsg;
        }
      }
      // Friendly, non-invasive weekend nudge: a calm info chip next to the
      // Synkroniser button (never red/error styling, no notification).
      const autoHour = a.auto_sync && a.auto_sync_hour !== null && a.auto_sync_hour !== undefined
        ? ` · synkroniseres automatisk dagligt ca. kl. ${String(a.auto_sync_hour).padStart(2, "0")}:17`
        : "";
      const sourceNote = backend !== "kmd"
        ? `<div class="src-note">ℹ️ Data fra ${esc(dataSource)}${has("hourly") ? "" : " · daglige aflæsninger"}${esc(autoHour)} · eksperimentel</div>`
        : "";
      // Subtle source line; only where outdoor temperatures are actually used.
      const wxHasTemps = Object.keys(wx.monthly_temp || {}).length > 0 || Object.keys(wx.daily_temp || {}).length > 0;
      const tempTxt = (has("monthly") || has("daily")) && wxHasTemps ? outdoorTempText(a, lang) : "";
      const tempSourceNote = tempTxt ? `<div class="src-note temp-src" data-section="temp-source">🌡️ ${esc(tempTxt)}</div>` : "";
      const feedbackFooter = `
            <div class="fb-foot">
              <span>📣 <b>Feedback om værker:</b> Virker <b>${esc(activeUtil.name)}</b> (uden persondata)?</span>
              <div class="bn-btns">
                <button class="btn primary" id="obFbGithubBtn">✅ Bekræft værk på GitHub ↗</button>
                <button class="btn" id="obFbIssueBtn">🐞 Fejlmeld værk ↗</button>
                <button class="btn" id="obFbCopyBtn">${this._fbCopied ? "✅ Kopieret!" : "📋 Kopiér teknisk rapport"}</button>
              </div>
            </div>`;
      const efOnboard = `
          <div class="onboard" id="onboardCard">
            <div class="ob-head">
              <div class="tb-left">
                <span class="tb-title">🔥 ${esc(activeUtil.name)} — ${esc(dataSource)}</span>
                <span class="badge ${utilStatus === "confirmed" ? "ok" : "warn"}">${esc(statusBadge)}</span>
              </div>
              <div class="bn-btns">
                ${!isInitialSetup ? `<button class="btn" id="closeSetupBtn">✕ Luk</button>` : ""}
              </div>
            </div>
            <div class="ob-note">Data fra ${esc(dataSource)}. ${esc(loginHow)} er sat op i Home Assistant (Indstillinger → Enheder &amp; tjenester). Tryk <b>🔄 Hent data nu</b> for synkronisering${autoHour ? "; der hentes også automatisk hver dag" : ""}.</div>
            ${(hasSyncMsg || this._startingSync) ? `<div class="ob-live ${hasSyncMsg && syncMsg.startsWith("Fejl") ? "red" : ""}">📡 ${esc(hasSyncMsg ? syncMsg : "Henter data…")}</div>` : ""}
            <div class="tb-actions">
              <button class="btn primary" id="efSyncBtn">🔄 Hent data nu</button>
            </div>
            <details class="ob-manual" ${!isInitialSetup ? "open" : ""}>
              <summary>⚙️ Valgfrit: Tilpas varmepris (kr./kWh) &amp; forventet returtemperatur</summary>
              <div style="display:flex;flex-direction:column;gap:10px;margin-top:8px">
                <div class="ob-note">Udfyld kun hvis du vil se estimeret forbrug i <b>kr./øre</b> eller overstyre ${backend === "eforsyning" ? "værkets / E|Forsynings" : "standard"} returgrænser (<code>0</code> = automatisk).</div>
                <div class="ob-grid">
                  <label class="ob-field">Varmepris inkl. moms (kr./kWh)
                    <input id="efPriceInput" type="number" step="0.001" value="${esc(wizEfPrice)}" placeholder="f.eks. 0.705" />
                  </label>
                  <label class="ob-field">Motivation (% pr. °C)
                    <input id="efMotivPctInput" type="number" step="0.1" value="${esc(wizEfMotivPct)}" placeholder="f.eks. 1" />
                  </label>
                  <label class="ob-field">Forventet retur / Bonus (°C)
                    <input id="efBonusInput" type="number" step="0.5" value="${esc(wizEfBonus)}" placeholder="${backend === "eforsyning" ? "Auto fra E|Forsyning" : "f.eks. 37"}" />
                  </label>
                  <label class="ob-field">Gebyrgrænse (°C, tom = samme)
                    <input id="efPenaltyInput" type="number" step="0.5" value="${esc(wizEfPenalty)}" placeholder="${allowBonus ? "Samme som forventet retur" : "Auto fra fremløb"}" />
                  </label>
                  ${(hasDynamicCurve || fwdTemp !== null) ? `<label class="ob-field">Fremløbstemperatur (°C, 0 = auto)
                    <input id="efForwardInput" type="number" step="0.5" value="${esc(wizEfForward)}" placeholder="${fwdTemp !== null && fwdSrc === "meter" ? `Auto (${fmtDec(fwdTemp)} °C fra måler)` : "f.eks. 65 (0 = auto)"}" />
                  </label>` : ""}
                  <label class="ob-field">Abonnement inkl. moms (kr./m²/år)
                    <input id="efFixedM2Input" type="number" step="0.01" value="${esc(wizEfFixedM2)}" placeholder="f.eks. 33.75 (0 = standard)" />
                  </label>
                  <label class="ob-field">Boligareal (m²)
                    <input id="efAreaM2Input" type="number" step="1" value="${esc(wizEfAreaM2)}" placeholder="f.eks. 162" />
                  </label>
                  <label class="ob-field">Fast årsabonnement / målerbidrag (kr./år)
                    <input id="efFixedYearInput" type="number" step="1" value="${esc(wizEfFixedYear)}" placeholder="f.eks. 787.5 (0 = ingen)" />
                  </label>
                </div>
                <div class="tb-actions">
                  <button class="btn" id="saveTariffBtn">💾 Gem pris &amp; returkrav</button>
                </div>
              </div>
            </details>${feedbackFooter}
          </div>`;
      const syncNudge = (syncReminder && !hasSyncMsg && syncReminderMsg)
        ? `<div class="sync-nudge" role="status"><span aria-hidden="true">💧</span><span>${esc(syncReminderMsg)}</span></div>`
        : "";
      const costHint = (!has("cost") && hasData && !isInitialSetup && isAdmin)
        ? `<div class="src-note" data-section="cost-hint">💰 Har du din kWh-pris? <button class="link-btn" id="costHintSetupBtn">Tilføj pris &amp; returkrav ⚙️</button></div>`
        : "";

      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; font-family: inherit; color: var(--primary-text-color); }
          .wrap { display: flex; flex-direction: column; gap: 14px; max-width: 1480px; margin: 0 auto; width: 100%; box-sizing: border-box; position: relative; }
          .topbar {
            display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;
            padding: 12px 16px; border-radius: 18px;
            background: color-mix(in srgb, var(--card-background-color, #fff) 68%, transparent);
            backdrop-filter: blur(16px) saturate(160%); -webkit-backdrop-filter: blur(16px) saturate(160%);
            border: 1px solid var(--ha-card-border-color, var(--divider-color, rgba(148,163,184,0.28))); box-shadow: 0 6px 20px rgba(0,0,0,0.08);
          }
          .tb-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
          .tb-title { font-size: 15px; font-weight: 800; }
          .tb-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
          select.util-sel {
            padding: 7px 10px; border-radius: 11px; font-size: 12.5px; font-weight: 600;
            background: var(--secondary-background-color, rgba(148,163,184,0.16));
            color: var(--primary-text-color); border: 1px solid rgba(148,163,184,0.35);
          }
          button.btn {
            padding: 7px 12px; border-radius: 11px; font-size: 12.5px; font-weight: 700; cursor: pointer;
            border: 1px solid rgba(148,163,184,0.35); background: rgba(249,115,22,0.16);
            color: var(--primary-text-color); transition: opacity 0.15s;
          }
          button.btn.login { background: rgba(14,165,233,0.18); border-color: rgba(14,165,233,0.4); }
          button.btn:hover { opacity: 0.85; }
          button.btn:focus-visible, .link-btn:focus-visible, .bn-main:focus-visible, .ob-field input:focus-visible, .ob-field select:focus-visible, details.ob-manual summary:focus-visible, rect[data-tip]:focus-visible, circle[data-tip]:focus-visible {
            outline: 2px solid var(--primary-color, #0284c7);
            outline-offset: 2px;
          }
          .badge {
            padding: 3px 9px; border-radius: 999px; font-size: 11.5px; font-weight: 700;
            background: rgba(148,163,184,0.16); border: 1px solid rgba(148,163,184,0.3);
          }
          .badge.ok { background: rgba(34,197,94,0.16); color: #16a34a; border-color: rgba(34,197,94,0.35); }
          .badge.warn { background: rgba(245,158,11,0.18); color: #d97706; border-color: rgba(245,158,11,0.35); }
          .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
          .kpi {
            padding: 13px 15px; border-radius: 18px; min-width: 0;
            background: color-mix(in srgb, var(--card-background-color, #fff) 64%, transparent);
            backdrop-filter: blur(16px) saturate(160%); -webkit-backdrop-filter: blur(16px) saturate(160%);
            border: 1px solid var(--ha-card-border-color, var(--divider-color, rgba(148,163,184,0.28))); box-shadow: 0 6px 20px rgba(0,0,0,0.08);
          }
          .k-lbl { font-size: 12px; font-weight: 700; color: var(--secondary-text-color); }
          .k-val { font-size: 21px; font-weight: 800; margin: 4px 0 2px; }
          .k-sub { font-size: 12px; font-weight: 600; color: var(--secondary-text-color); }
          .good { color: #16a34a; } .warn { color: #d97706; } .bad { color: #dc2626; }
          .grid2 { display: grid; grid-template-columns: 1fr; gap: 14px; }
          .panel {
            padding: 16px 18px; border-radius: 20px; position: relative; min-width: 0;
            background: color-mix(in srgb, var(--card-background-color, #fff) 64%, transparent);
            backdrop-filter: blur(16px) saturate(160%); -webkit-backdrop-filter: blur(16px) saturate(160%);
            border: 1px solid var(--ha-card-border-color, var(--divider-color, rgba(148,163,184,0.28))); box-shadow: 0 8px 26px rgba(0,0,0,0.10);
          }
          .p-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
          .p-title { font-size: 15.5px; font-weight: 800; }
          .p-leg { font-size: 12.5px; color: var(--secondary-text-color); display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
          .p-leg span { display: inline-flex; align-items: center; white-space: nowrap; }
          .dot { display: inline-block; width: 9px; height: 9px; border-radius: 3px; margin-right: 4px; vertical-align: middle; }
          .svg { width: 100%; height: auto; display: block; overflow: visible; }
          .ax { font-size: 13px; fill: var(--primary-text-color, #1e293b); opacity: 0.88; font-weight: 600; }
          .ax-sub { font-size: 11.5px; fill: var(--secondary-text-color, #64748b); font-weight: 600; }
          .ax-unit { font-size: 11px; fill: var(--secondary-text-color, #64748b); font-weight: 700; }
          .ax-t { font-size: 12.5px; fill: var(--kmd-temp-axis-color, #0284c7); font-weight: 700; }
          .ax-bonus { font-size: 12.5px; fill: var(--kmd-bonus-axis-color, #16a34a); font-weight: 700; }
          .ax-penalty { font-size: 12.5px; fill: var(--kmd-penalty-axis-color, #dc2626); font-weight: 700; }
          .val { font-size: 12px; fill: var(--primary-text-color, #0f172a); font-weight: 800; paint-order: stroke; stroke: var(--card-background-color, #ffffff); stroke-width: 4px; stroke-linejoin: round; }
          .val-sm { font-size: 11.5px; }
          .val-lg { font-size: 13px; }
          rect[data-tip], circle[data-tip] { cursor: pointer; transition: opacity 0.12s ease; }
          rect[data-tip]:hover, circle[data-tip]:hover { opacity: 0.78; }
          .tip {
            position: sticky; bottom: 8px; padding: 7px 12px; border-radius: 12px;
            background: rgba(15, 23, 42, 0.88); color: #fff; font-size: 12.5px; font-weight: 600;
            text-align: center; display: none; margin-top: 4px;
          }
          .tip.on { display: block; }
          .float-tip {
            position: absolute; pointer-events: none; z-index: 20; max-width: min(360px, 90vw);
            padding: 7px 11px; border-radius: 10px; background: rgba(15, 23, 42, 0.94); color: #f8fafc;
            font-size: 12.5px; font-weight: 600; box-shadow: 0 8px 20px rgba(0,0,0,0.25);
            opacity: 0; visibility: hidden; transform: translate(-50%, -100%); transition: opacity 0.12s ease;
            white-space: normal; text-align: center;
          }
          .float-tip.below { transform: translate(-50%, 0); }
          .float-tip.on { opacity: 1; visibility: visible; }
          .insights { display: grid; grid-template-columns: 1fr; gap: 10px; }
          .ins {
            padding: 13px 15px; border-radius: 16px; min-width: 0;
            background: color-mix(in srgb, var(--card-background-color, #fff) 55%, transparent);
            border: 1px solid rgba(148,163,184,0.22); font-size: 13px; line-height: 1.5;
          }
          .ins-title { display: block; margin-bottom: 5px; font-size: 13.5px; font-weight: 800; color: var(--primary-text-color); }
          .ins b { font-weight: 700; color: var(--primary-text-color); }
          .fb-bar {
            display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;
            padding: 10px 14px; border-radius: 16px; font-size: 12.5px; font-weight: 600;
            background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.35);
          }
          .fb-foot {
            display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;
            padding-top: 8px; border-top: 1px solid rgba(148,163,184,0.22); font-size: 12.5px; color: var(--secondary-text-color);
          }
          .hdd-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
          .hdd-pill {
            padding: 4px 9px; border-radius: 10px; font-size: 12px; font-weight: 700;
            background: rgba(245,158,11,0.16); border: 1px solid rgba(245,158,11,0.3);
          }
          .src-note { font-size: 12px; color: var(--secondary-text-color); margin-top: -6px; padding: 0 4px; }
          .link-btn { background: none; border: none; padding: 0; font: inherit; font-weight: 700; color: #0284c7; cursor: pointer; text-decoration: underline; }
          .sync-nudge {
            display: flex; align-items: center; gap: 8px; margin-top: -6px;
            padding: 7px 12px; border-radius: 999px; font-size: 12.5px; font-weight: 600; line-height: 1.35;
            color: var(--secondary-text-color);
            background: rgba(14,165,233,0.08); border: 1px solid rgba(14,165,233,0.22);
          }
          .fresh-pill {
            padding: 3px 9px; border-radius: 999px; font-size: 11.5px; font-weight: 700;
            background: rgba(148,163,184,0.16); border: 1px solid rgba(148,163,184,0.3);
          }
          .fresh-pill.today { background: rgba(34,197,94,0.16); color: #16a34a; border-color: rgba(34,197,94,0.35); }
          .banner {
            display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
            padding: 12px 16px; border-radius: 18px;
            background: color-mix(in srgb, var(--card-background-color, #fff) 68%, transparent);
            backdrop-filter: blur(16px) saturate(160%); -webkit-backdrop-filter: blur(16px) saturate(160%);
            border: 1px solid var(--ha-card-border-color, var(--divider-color, rgba(148,163,184,0.28))); box-shadow: 0 6px 20px rgba(0,0,0,0.08);
          }
          .bn-main { display: flex; align-items: center; gap: 12px; cursor: pointer; flex: 0 1 auto; min-width: 220px; max-width: 100%; border-radius: 12px; padding: 2px 4px; margin: -2px -4px; }
          .bn-ico {
            width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center;
            font-size: 16px; font-weight: 800; flex-shrink: 0;
            background: rgba(249,115,22,0.18); color: #ea580c;
          }
          .bn-ico.ok { background: rgba(34,197,94,0.18); color: #16a34a; }
          .bn-ico.blue { background: rgba(14,165,233,0.18); color: #0284c7; }
          .bn-ico.amber { background: rgba(245,158,11,0.18); color: #d97706; }
          .bn-ico.red { background: rgba(239,68,68,0.18); color: #dc2626; }
          .bn-txt { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
          .bn-title { font-size: 14.5px; font-weight: 800; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
          .bn-sub { font-size: 12px; font-weight: 600; color: var(--secondary-text-color); }
          .bn-btns { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
          .onboard {
            padding: 18px 20px; border-radius: 20px; display: flex; flex-direction: column; gap: 14px;
            background: color-mix(in srgb, var(--card-background-color, #fff) 76%, transparent);
            backdrop-filter: blur(16px) saturate(160%); -webkit-backdrop-filter: blur(16px) saturate(160%);
            border: 1px solid rgba(14,165,233,0.40); box-shadow: 0 8px 28px rgba(0,0,0,0.12);
          }
          .ob-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
          .ob-note { font-size: 13px; color: var(--secondary-text-color); line-height: 1.45; }
          .ob-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; align-items: start; }
          .ob-field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; font-weight: 700; color: var(--secondary-text-color); min-width: 0; }
          .ob-field label { font-size: 12px; font-weight: 700; color: var(--secondary-text-color); }
          .ob-field input, .ob-field select {
            width: 100%; max-width: 100%; min-width: 0; box-sizing: border-box; text-overflow: ellipsis;
            padding: 8px 10px; border-radius: 10px; font-size: 13px; font-weight: 600;
            background: var(--secondary-background-color, rgba(148,163,184,0.16));
            color: var(--primary-text-color); border: 1px solid rgba(148,163,184,0.35);
          }
          .ob-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; }
          .ob-step { font-size: 13.5px; font-weight: 800; color: var(--primary-text-color); margin-top: 2px; }
          .ob-guide {
            padding: 10px 13px; border-radius: 12px; font-size: 13px; line-height: 1.5;
            background: rgba(14,165,233,0.10); border: 1px solid rgba(14,165,233,0.28);
          }
          .ob-guide ol { margin: 4px 0 0 18px; padding: 0; }
          .ob-live { padding: 9px 12px; border-radius: 12px; font-size: 13px; font-weight: 700; background: rgba(245,158,11,0.15); border: 1px solid rgba(245,158,11,0.38); }
          .ob-live.blue { background: rgba(14,165,233,0.16); border-color: rgba(14,165,233,0.42); }
          .ob-live.red { background: rgba(239,68,68,0.16); border-color: rgba(239,68,68,0.42); color: #dc2626; }
          .mitid-box {
            padding: 14px 16px; border-radius: 14px; text-align: center; font-size: 13.5px; font-weight: 700;
            max-width: 540px; margin: 0 auto; width: 100%; box-sizing: border-box;
            background: rgba(14,165,233,0.14); border: 2px solid rgba(14,165,233,0.5);
          }
          .otp-digits { font-size: 32px; font-weight: 900; letter-spacing: 6px; margin-top: 6px; color: #0284c7; }
          .qr-wrap { margin: 10px auto 0; width: min(240px, 70vw); aspect-ratio: 1 / 1; box-sizing: content-box; background: #fff; padding: 14px; border-radius: 12px; }
          .qr-wrap img, .qr-wrap svg { width: 100%; height: 100%; display: block; image-rendering: pixelated; }
          .qr-hint { margin: 8px auto 0; max-width: 54ch; line-height: 1.45; font-size: 12px; font-weight: 600; color: var(--secondary-text-color); }
          details.ob-manual { font-size: 12.5px; color: var(--secondary-text-color); padding-top: 4px; border-top: 1px solid rgba(148,163,184,0.22); }
          details.ob-manual summary { cursor: pointer; font-weight: 700; padding: 4px 0; }
          button.btn.primary { background: rgba(34,197,94,0.20); border-color: rgba(34,197,94,0.45); }
          button.btn:disabled { opacity: 0.55; cursor: wait; }
          @media (min-width: 560px) and (max-width: 959px) {
            .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          }
          @media (min-width: 960px) {
            .kpis { grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
          }
          @media (min-width: 768px) {
            .grid2 { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
            .grid2 > .panel:last-child:nth-child(odd) { grid-column: 1 / -1; }
            .grid2 > .panel:last-child:nth-child(odd) .svg { max-height: 285px; }
          }
          @media (min-width: 600px) and (max-width: 1199px) {
            .insights { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          }
          @media (min-width: 1200px) {
            .insights { grid-template-columns: repeat(auto-fit, minmax(195px, 1fr)); gap: 12px; }
          }
          @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { transition: none !important; animation: none !important; }
          }
          @media (prefers-color-scheme: dark) {
            .good, .badge.ok, .fresh-pill.today, .bn-ico.ok { color: #4ade80; }
            .warn, .badge.warn, .bn-ico.amber { color: #fbbf24; }
            .bad, .bn-ico.red, .ob-live.red { color: #f87171; }
            .bn-ico.blue, .link-btn, .otp-digits { color: #38bdf8; }
            .ax-t { fill: #38bdf8; }
            .ax-bonus { fill: #4ade80; }
            .ax-penalty { fill: #f87171; }
            .val { fill: var(--primary-text-color, #f8fafc); stroke: var(--card-background-color, #1c1c1c); }
          }
        </style>
        <div class="wrap" id="wrap">
          ${cfg.show_sync_bar !== false ? (showOnboarding && !hasMitid ? efOnboard : showOnboarding ? `
          <div class="onboard" id="onboardCard">
            <div class="ob-head">
              <div class="tb-left">
                <span class="tb-title">🔥 ${isInitialSetup ? "Førstegangsopsætning — KMD Easy Energy Fjernvarme" : "Skift / test værk & indstillinger"}</span>
                <span class="badge ${activeUtil.status === "confirmed" ? "ok" : "warn"}">${activeUtil.status === "confirmed" ? esc(t.confirmed) : esc(t.pending)}</span>
              </div>
              <div class="bn-btns">
                ${!isInitialSetup ? `<button class="btn" id="resetSetupBtn">↺ Nulstil til 1.-gangs opsætning</button><button class="btn" id="closeSetupBtn">✕ Luk</button>` : ""}
              </div>
            </div>
            <div class="ob-step">1. Vælg dit forsyningsselskab &amp; MitID Bruger-ID</div>
            <div class="ob-grid">
              <label class="ob-field">Forsyningsselskab (KMD Easy Energy)
                <select id="utilSel" aria-label="Select utility login">
                  <optgroup label="${esc(t.confirmed_grp)}">${confirmedOpts}</optgroup>
                  <optgroup label="${esc(t.pending_grp)}">${pendingOpts}</optgroup>
                </select>
              </label>
              ${activeUtilId === "custom" ? `<label class="ob-field">Login-portal URL
                <input id="portalUrlInput" value="${esc(wizPortalUrl)}" />
              </label>` : ""}
              <label class="ob-field">MitID Bruger-ID (gemmes kun lokalt i HA)
                <input id="mitidUserInput" value="${esc(this._wizMitidUser || "")}" placeholder="${hasMitidUser ? `Gemt i HA (${esc(mitidMasked)}) — udfyld kun for at ændre` : "Indtast dit MitID Bruger-ID"}" />
              </label>
              <div class="ob-field"><label for="notifySel">Mobil Push-service (valgfri, til kode på telefon)</label>
                ${notifySelectHtml}
              </div>
            </div>
            <details class="ob-manual" ${!isInitialSetup ? "open" : ""}>
              <summary>⚙️ Avanceret (valgfrit): Varmepris (kr./kWh), returkrav &amp; lokation</summary>
              <div class="ob-grid" style="margin-top:8px">
                ${activeUtilId !== "custom" ? `<label class="ob-field">Login-portal URL
                  <input id="portalUrlInput" value="${esc(wizPortalUrl)}" />
                </label>` : ""}
                <label class="ob-field">By / Lokation (Open-Meteo vejr)
                  <input id="locInput" value="${esc(wizLocation)}" />
                </label>
                <div class="ob-field"><span>Retur Bonus / Gebyr (°C)</span>
                  <div class="ob-pair">
                    <input id="bonusInput" type="number" step="0.5" value="${esc(wizBonus)}" aria-label="Retur Bonus (°C)" />
                    <input id="penaltyInput" type="number" step="0.5" value="${esc(wizPenalty)}" aria-label="Retur Gebyr (°C)" />
                  </div>
                </div>
                <div class="ob-field"><span>Varmepris (kr./kWh) &amp; Motivation (%/°C)</span>
                  <div class="ob-pair">
                    <input id="priceInput" type="number" step="0.001" value="${esc(wizPrice)}" placeholder="kr./kWh" aria-label="Varmepris (kr./kWh)" />
                    <input id="motivPctInput" type="number" step="0.1" value="${esc(wizMotivPct)}" placeholder="%/°C" aria-label="Motivation (%/°C)" />
                  </div>
                </div>
                <div class="ob-field"><span>Abonnement (kr./m²/år) &amp; Boligareal (m²)</span>
                  <div class="ob-pair">
                    <input id="fixedM2Input" type="number" step="0.01" value="${esc(wizFixedM2)}" placeholder="kr./m²/år" aria-label="Abonnement (kr./m²/år)" />
                    <input id="areaM2Input" type="number" step="1" value="${esc(wizAreaM2)}" placeholder="m²" aria-label="Boligareal (m²)" />
                  </div>
                </div>
                <label class="ob-field">Fast årsabonnement / målerbidrag (kr./år)
                  <input id="fixedYearInput" type="number" step="1" value="${esc(wizFixedYear)}" placeholder="kr./år (valgfri)" />
                </label>
              </div>
            </details>
            <div class="ob-step">2. Forbind med 1-klik MitID-synkronisering (Anbefalet — 100% i Home Assistant)</div>
            <div class="ob-guide">
              <ol>
                <li>Udfyld dit <b>MitID Bruger-ID</b> ovenfor og tryk på <b>🚀 Gem &amp; Start MitID-synkronisering</b> herunder <i>(åbn ikke selv værkets hjemmeside i browseren)</i>.</li>
                <li><b>Åbn straks MitID-appen på din telefon og lås den op</b> <i>(vigtigt: MitID genererer først QR-koden / den 4-cifrede kode i det øjeblik, du åbner MitID-appen!)</i>.</li>
                <li><b>Opsætter du på en tablet eller computer:</b> scan QR-koden her på kortet med MitID-appen på telefonen og godkend. <b>Opsætter du på samme telefon som MitID-appen:</b> indtast de <b>4 cifre</b> fra kortet (eller push-notifikationen) i MitID-appen og godkend — det kræver engangskoder slået til (se herunder).</li>
              </ol>
              <div class="ob-note" style="margin-top:6px">ℹ️ Hver synkronisering er ét MitID-login: data siden sidste synkronisering hentes, og adgangen fra KMD (gyldig ca. 1 time) kasseres straks. Integrationen henter ikke data i baggrunden — tryk <b>🔄 Synkroniser</b>, når du vil have nye tal (f.eks. dagligt eller ugentligt).</div>
            </div>
            ${this._mitidErr ? `<div class="ob-live red">⚠️ ${esc(this._mitidErr)}</div>` : ""}
            ${(hasSyncMsg || this._startingSync) ? `<div class="ob-live ${hasSyncMsg && syncMsg.startsWith("Fejl") ? "red" : (hasSyncMsg && syncMsg.includes("MitID") ? "blue" : "")}">📡 ${esc(hasSyncMsg ? syncMsg : "Starter MitID-login…")}</div>` : ""}
            ${mitidLiveBox}
            <div class="tb-actions">
              <button class="btn primary" id="startMitidBtn" ${this._startingSync ? "disabled" : ""}>🚀 Gem &amp; Start MitID-synkronisering</button>
              ${hasData ? `<button class="btn" id="completeNowBtn">⚡ Hurtig-test: Vis dashboard med eksisterende data</button>` : ""}
            </div>
            <details class="ob-manual">
              <summary>📲 Kun hvis du opsætter på samme telefon som MitID-appen: Slå 4-cifret engangskode til</summary>
              <div class="ob-note" style="margin:8px 0">
                <b>Tablet eller computer + MitID-app på telefonen:</b> Du behøver ikke ændre noget. Scan blot QR-koden, der vises her på kortet, med MitID-appen og godkend.<br/>
                <b>Samme telefon:</b> MitID viser som standard en animeret <b>QR-kode</b>, og den kan ikke scannes med den telefon, den står på. Skift derfor til 4-cifrede engangskoder én gang for alle:<br/>
                <b>MitID-app → Menu (⚙️ øverst) → Godkend med QR- eller engangskoder → Engangskoder</b>.<br/>
                <i>Bemærk: MitID har af sikkerhedshensyn 24 timers ventetid ved første skift fra QR-kode til engangskode, hvorefter du bekræfter skiftet i appen.</i>
              </div>
            </details>
            <details class="ob-manual">
              <summary>🛠️ Manuelt login i browser / Første konto-aktivering hos værket</summary>
              <div class="ob-note" style="margin:8px 0">
                Brug kun dette, hvis du <b>(a)</b> aldrig har aktiveret din konto hos værket før (kræver kundenr. + aktiveringskode fra regning 1. gang), eller <b>(b)</b> vil logge ind manuelt i browseren og indsætte et Bearer token herunder. Tokenet bruges til <b>én</b> synkronisering og gemmes ikke. Luk browser-fanen igen, før du bruger 1-klik MitID-sync.
              </div>
              <div style="margin-bottom:8px">
                <button class="btn login" id="loginBtn" title="${esc(wizPortalUrl)}">🔑 Åbn ${esc(activeUtil.name)} login-portal i browser ↗</button>
              </div>
              <div class="ob-grid">
                <label class="ob-field">Bearer access token
                  <input id="manualTokenInput" type="password" placeholder="Indsæt token..." />
                </label>
                <label class="ob-field">Customer-Id (valgfri)
                  <input id="manualCustIdInput" placeholder="Valgfrit UUID" />
                </label>
              </div>
              <div style="margin-top:8px">
                <button class="btn primary" id="saveTokenBtn">▶️ Synkroniser én gang med token</button>
              </div>
            </details>${feedbackFooter}
          </div>` : `
          <div class="banner">
            <div class="bn-main" id="syncTap" role="button" tabindex="0" title="Tryk for at synkronisere">
              <div class="bn-ico ${bannerTone}">${bannerIcon}</div>
              <div class="bn-txt">
                <div class="bn-title">
                  <span>${esc(bannerTitle)}</span>
                  <span class="badge ${utilStatus === "confirmed" ? "ok" : "warn"}">${esc(statusBadge)}</span>
                </div>
                <div class="bn-sub">${esc(bannerSub)}</div>
              </div>
            </div>
            <div class="bn-btns">
              <button class="btn login" id="loginBtn" title="${esc(activePortalUrl)}">🔑 Portal ↗</button>
              <button class="btn" id="syncBtn">${esc(t.sync_btn)}</button>
              ${isAdmin ? `<button class="btn" id="openSetupBtn" title="Skift værk / opsætning">⚙️</button>` : ""}
            </div>
          </div>
          ${syncNudge}
          ${sourceNote}
          ${tempSourceNote}
          ${mitidLiveBox}
          ${costHint}
          ${(utilStatus !== "confirmed" && hasData) ? `
          <div class="fb-bar">
            <span>🎉 Virker <b>${esc(activeUtil.name)}</b> hos dig? Hjælp med at flytte værket til ✅ Bekræftet:</span>
            <div class="bn-btns">
              <button class="btn primary" id="fbGithubBtn">📣 Bekræft på GitHub ↗</button>
              <button class="btn" id="fbIssueBtn">🐞 Fejlmeld ↗</button>
              <button class="btn" id="fbCopyBtn">${this._fbCopied ? "✅ Kopieret!" : "📋 Kopiér rapport"}</button>
            </div>
          </div>` : ""}`) : ""}

          ${isInitialSetup ? "" : `

          <div class="kpis">
            <div class="kpi">
              <div class="k-lbl">${esc(t.kpi_ytd)} ${curYr} (ÅTD)</div>
              <div class="k-val">${fmtInt(yCur)} kWh</div>
              <div class="k-sub">${yPrev > 0 ? `${prevYr} hele år: ${fmtInt(yPrev)} kWh` : (lang === "en" ? "Year-to-date" : "År-til-dato")}</div>
            </div>
            ${has("temperatures") ? `<div class="kpi">
              <div class="k-lbl">${esc(t.kpi_ret)} ${curYr}</div>
              <div class="k-val ${rtCur > 0 ? (!allowBonus ? (rtCur <= penaltyT ? "good" : "bad") : (rtCur < bonusT ? "good" : (rtCur <= penaltyT ? "warn" : "bad"))) : ""}">${rtCur > 0 ? `${fmtDec(rtCur)} °C` : "–"}</div>
              <div class="k-sub">${!allowBonus ? `${rtCur > 0 ? (rtCur <= penaltyT ? `🟢 OK (≤${penaltyT} °C)` : `+${fmtDec(rtCur - penaltyT)} °C over krav (${penaltyT} °C)`) : `Krav: ≤${penaltyT} °C`}${fwdTemp !== null ? ` · frem ${fmtDec(fwdTemp)} °C` : ""}` : (singleReturnTarget ? (rtCur > 0 ? (rtCur < bonusT ? `🟢 Under krav (<${bonusT} °C)` : (rtCur > penaltyT ? `+${fmtDec(rtCur - penaltyT)} °C over krav (${penaltyT} °C)` : `På forventet retur (${bonusT} °C)`)) : `Forventet retur: ${bonusT} °C`) : (rtCur > 0 ? (rtCur < bonusT ? `🟢 Bonus-zone (<${bonusT} °C)` : `${fmtDec(rtCur - bonusT)} °C til bonus (<${bonusT} °C)`) : `Grænser: <${bonusT}° bonus / >${penaltyT}° gebyr`))}</div>
            </div>` : ""}
            ${has("forecast") ? `<div class="kpi">
              <div class="k-lbl">${esc(t.kpi_fc)}</div>
              <div class="k-val good">${expK > 0 ? `${fmtInt(expK)} kWh` : "–"}</div>
              <div class="k-sub">${budK > 0 ? `${fcPct}% mod budget (${fmtInt(budK)} kWh)` : esc(fc.period || "–")}</div>
            </div>` : ""}
            ${has("billing") ? `<div class="kpi">
              <div class="k-lbl">${esc(t.kpi_bill)} ${curYr}</div>
              <div class="k-val">${fmtInt(bl[`total_${curYr}_kr`] ?? bl.total_2026_kr ?? 0)} kr.</div>
              <div class="k-sub">Saldo ${fmtDec(bl.saldo_kr ?? 0, 2)} kr.${bl.last_bill_date ? ` · ${esc(bl.last_bill_date)}` : ""}</div>
            </div>` : ""}
          </div>

          ${(has("cost") && (
            typeof costEst.latest_day_dkk === "number"
            || typeof costEst.current_month_dkk === "number"
            || typeof costEst.ytd_dkk === "number"
            || typeof costEst.forecast_annual_dkk === "number"
            || typeof costEst.effective_price_dkk_per_kwh === "number"
          )) ? (() => {
            const hasFixedFee = costEst.excludes_fixed_fees === false
              && typeof costEst.annual_fixed_fee_dkk === "number"
              && costEst.annual_fixed_fee_dkk > 0;
            const hasBase = typeof costEst.base_price_dkk_per_kwh === "number";
            const baseTxt = hasBase ? `${fmtDec(costEst.base_price_dkk_per_kwh, 3)} kr/kWh` : "";
            const adj = costEst.adjustment_pct;
            let effSub = "";
            if (typeof adj === "number" && adj < 0) {
              effSub = `<span class="good">${fmtDec(Math.abs(adj), 1)} % bonus</span>${hasBase ? ` · ${lang === "en" ? "base" : "grundpris"} ${baseTxt}` : ""}`;
            } else if (typeof adj === "number" && adj > 0) {
              effSub = `<span class="bad">+${fmtDec(adj, 1)} % ${lang === "en" ? "surcharge" : "gebyr"}</span>${hasBase ? ` · ${lang === "en" ? "base" : "grundpris"} ${baseTxt}` : ""}`;
            } else if (hasBase) {
              effSub = `${lang === "en" ? "Base price" : "Grundpris"} ${baseTxt}`;
            }
            const panelTitle = hasFixedFee
              ? (lang === "en" ? `💰 Estimated cost (${curYr})` : `💰 Estimeret udgift (${curYr})`)
              : (lang === "en" ? `💰 Estimated variable cost (${curYr})` : `💰 Estimeret forbrug i kr. (${curYr})`);
            const panelLegend = hasFixedFee
              ? (lang === "en"
                ? `Incl. fixed fee (${fmtInt(costEst.annual_fixed_fee_dkk)} DKK/yr) · estimate, not invoice`
                : `Inkl. fast bidrag (${fmtInt(costEst.annual_fixed_fee_dkk)} kr./år) · estimat, ikke regningen`)
              : (lang === "en" ? "Excl. fixed fees · estimate, not invoice" : "Ekskl. faste afgifter · estimat, ikke regningen");
            const monthFixedTxt = (hasFixedFee && typeof costEst.current_month_fixed_dkk === "number" && costEst.current_month_fixed_dkk > 0)
              ? ` · ${lang === "en" ? "incl." : "inkl."} ${fmtInt(costEst.current_month_fixed_dkk)} kr. ${lang === "en" ? "fixed" : "fast"}`
              : "";
            const ytdFixedTxt = (hasFixedFee && typeof costEst.ytd_fixed_dkk === "number" && costEst.ytd_fixed_dkk > 0)
              ? ` · ${lang === "en" ? "incl." : "inkl."} ${fmtInt(costEst.ytd_fixed_dkk)} kr. ${lang === "en" ? "fixed" : "fast"}`
              : "";
            return `<div class="panel" data-section="cost-estimate">
              <div class="p-head">
                <div class="p-title">${panelTitle}</div>
                <div class="p-leg"><span>${panelLegend}</span></div>
              </div>
              <div class="kpis">
                ${typeof costEst.latest_day_dkk === "number" ? `<div class="kpi">
                  <div class="k-lbl">${lang === "en" ? "Latest day" : "Seneste døgn"}</div>
                  <div class="k-val">~${fmtInt(costEst.latest_day_dkk)} kr.</div>
                  <div class="k-sub">${typeof costEst.latest_day_kwh === "number" ? `${fmtInt(costEst.latest_day_kwh)} kWh` : ""}${costEst.latest_day_label ? `${typeof costEst.latest_day_kwh === "number" ? " · " : ""}${esc(costEst.latest_day_label)}` : ""}</div>
                </div>` : ""}
                ${typeof costEst.current_month_dkk === "number" ? `<div class="kpi">
                  <div class="k-lbl">${lang === "en" ? "This month" : "Denne måned"}</div>
                  <div class="k-val">~${fmtInt(costEst.current_month_dkk)} kr.</div>
                  <div class="k-sub">${typeof costEst.current_month_kwh === "number" ? `${fmtInt(costEst.current_month_kwh)} kWh` : ""}${monthFixedTxt}</div>
                </div>` : ""}
                ${typeof costEst.ytd_dkk === "number" ? `<div class="kpi">
                  <div class="k-lbl">${lang === "en" ? `Year to date (${curYr})` : `I år (${curYr})`}</div>
                  <div class="k-val">~${fmtInt(costEst.ytd_dkk)} kr.</div>
                  <div class="k-sub">${yCur > 0 ? `${fmtInt(yCur)} kWh` : ""}${ytdFixedTxt}</div>
                </div>` : ""}
                ${typeof costEst.forecast_annual_dkk === "number" ? `<div class="kpi">
                  <div class="k-lbl">${lang === "en" ? "Expected annual cost" : "Forventet årsudgift"}</div>
                  <div class="k-val">~${fmtInt(costEst.forecast_annual_dkk)} kr.</div>
                  <div class="k-sub">${typeof costEst.forecast_annual_kwh === "number" ? `${fmtInt(costEst.forecast_annual_kwh)} kWh` : ""}${hasFixedFee ? `${typeof costEst.forecast_annual_kwh === "number" ? " · " : ""}${lang === "en" ? "incl." : "inkl."} ${fmtInt(costEst.annual_fixed_fee_dkk)} kr. ${lang === "en" ? "fixed" : "fast"}` : ""}</div>
                </div>` : ""}
                ${typeof costEst.effective_price_dkk_per_kwh === "number" ? `<div class="kpi">
                  <div class="k-lbl">${lang === "en" ? "Effective price" : "Effektiv pris"}</div>
                  <div class="k-val">${fmtDec(costEst.effective_price_dkk_per_kwh, 3)} kr/kWh</div>
                  <div class="k-sub">${effSub}</div>
                </div>` : ""}
              </div>
            </div>`;
          })() : ""}

          ${(has("monthly") || has("temperatures") || has("hourly") || has("daily")) ? `<div class="grid2">
            ${has("monthly") ? `<div class="panel" data-section="monthly">
              <div class="p-head">
                <div class="p-title">📊 Månedligt forbrug: ${curYr} vs. ${prevYr} &amp; Udetemp</div>
                <div class="p-leg">
                  <span><i class="dot" style="background:#f97316"></i>${curYr} kWh</span>
                  <span><i class="dot" style="background:rgba(148,163,184,0.6)"></i>${prevYr} kWh</span>
                  <span><i class="dot" style="background:#38bdf8"></i>${esc(t.outdoor)} °C</span>
                </div>
              </div>
              ${this._renderMonthlySvg(mCur, mPrev, wx.monthly_temp || {}, curYr, prevYr, t, costEst.monthly_dkk || {})}
            </div>` : ""}

            ${has("temperatures") ? `<div class="panel" data-section="return-temp">
              <div class="p-head">
                <div class="p-title">${(singleReturnTarget || hasExpMonthly) ? `🎯 Returtemperatur ${curYr} (°C) vs. ${!allowBonus ? "Afkølingskrav" : "Forventet retur"} (${expRangeTxt})${hasDynamicCurve ? " · Dynamisk (fremløb)" : (fwdSrc === "manual" ? " · Manuel fremløb" : ((efExpectedRt !== null || hasExpMonthly) ? " · E|Forsyning" : ""))}` : `🎯 Returtemperatur ${curYr} (°C) vs. Bonus (${bonusT}°) &amp; Gebyr (${penaltyT}°)`}</div>
                <div class="p-leg">
                  ${!allowBonus ? `<span><i class="dot" style="background:#22c55e"></i>OK (≤ krav)</span><span><i class="dot" style="background:#ef4444"></i>Gebyr (&gt; krav)</span>` : ((singleReturnTarget || hasExpMonthly) ? `<span><i class="dot" style="background:#22c55e"></i>Under krav (bonus)</span><span><i class="dot" style="background:#ef4444"></i>Over krav (gebyr)</span>` : `<span><i class="dot" style="background:#22c55e"></i>Bonus &lt;${bonusT}°</span><span><i class="dot" style="background:#f59e0b"></i>Neutral</span><span><i class="dot" style="background:#ef4444"></i>Gebyr &gt;${penaltyT}°</span>`)}
                  ${expMList.length >= 2 ? `<span><i class="dot" style="background:#38bdf8"></i>${!allowBonus ? "Afkølingskrav °C" : "Forventet retur °C"}</span>` : ""}
                </div>
              </div>
              ${this._renderReturnTempSvg(rtM, bonusT, penaltyT, curYr, rtExpM, allowBonus)}
            </div>` : ""}

            ${has("hourly") ? `<div class="panel" data-section="hourly">
              <div class="p-head">
                <div class="p-title">🚿 Timeprofil · ${esc(hr.period || `${curYr} MTD`)} (snit pr. time)</div>
                <div class="p-leg">
                  <span><i class="dot" style="background:#ec4899"></i>${esc(peakLegendTxt)}</span>
                  <span><i class="dot" style="background:#38bdf8"></i>Retur °C</span>
                </div>
              </div>
              ${this._renderHourlyAvgSvg(hr, allowBonus ? bonusT : penaltyT, peakInfo)}
            </div>` : ""}

            ${has("daily") ? `<div class="panel" data-section="mtd-ytd">
              <div class="p-head">
                <div class="p-title">⚖️ Døgnforbrug: Måned-til-dato (MTD) vs. År-til-dato (YTD)</div>
                <div class="p-leg"><span>Gennemsnit pr. dag (${esc(t.avg_day)})</span></div>
              </div>
              ${this._renderMtdVsYtdSvg(ann, mPrev, dy, curYr, prevYr)}
            </div>` : ""}

            ${has("daily") ? `<div class="panel" data-section="daily">
              <div class="p-head">
                <div class="p-title">📅 ${esc(dy.month || `${curYr}`)}: Dagligt forbrug (kWh) &amp; Udetemp</div>
                <div class="p-leg">
                  <span>Snit ${fmtDec(dy.gennemsnit || 0)} ${esc(t.avg_day)}</span>
                  <span><i class="dot" style="background:#38bdf8"></i>${esc(t.outdoor)} °C</span>
                </div>
              </div>
              ${this._renderDailySvg(dy, wx.daily_temp || {}, t, wideDaily)}
            </div>` : ""}
          </div>` : ""}

          <div class="panel">
            <div class="p-head">
              <div class="p-title">🧠 Indsigter &amp; Udvikling (${esc(locName)} vejrkorreleret)</div>
              <div class="p-leg"><span class="fresh-pill${isToday ? " today" : ""}">${isToday ? "🟢 " : ""}${esc(freshText)}</span></div>
            </div>
            <div class="insights">
              ${ins.temp_r2_pct != null || ins.baseload_kwh_mo != null ? `<div class="ins">
                <div class="ins-title">🌡️ ${ins.temp_r2_reliable ? `${esc(ins.temp_r2_pct)}% styret af udetemperaturen` : (ins.temp_r2_pct != null ? `Kun ${esc(ins.temp_r2_pct)}% samvariation med udetemperaturen` : "Udetemperatur-sammenhæng")}</div>
                ${ins.temp_r2_reliable
                  ? `Månedligt forbrug følger ${esc(locName)}-temperaturen tæt (R² = ${esc(ins.temp_r2_pct)}%).`
                  : (ins.temp_r2_pct != null
                    ? `Månedligt forbrug følger ikke udetemperaturen tydeligt (R² = ${esc(ins.temp_r2_pct)}%). Tjek at kortet viser fjernvarme og ikke el, og at måneder uden data er sprunget over.`
                    : `Ikke nok komplette måneder til at beregne sammenhængen med udetemperaturen.`)}
                ${ins.baseload_kwh_mo != null ? ` Grundlast til varmt brugsvand + tomgang er <b>~${fmtDec(ins.baseload_kwh_mo, 0)} kWh/md</b> (~${fmtDec(baseDayKwh, 1)} kWh/dag om sommeren).` : ""}
              </div>` : ""}
              ${has("hourly") ? `<div class="ins" data-section="ins-hourly">
                <div class="ins-title">🚿 Døgnrytme (${esc(hr.days_averaged || Object.keys(dy.days || {}).length)}-dages MTD)</div>
                Højeste spidstime er kl. <b>${String(peakHourIdx).padStart(2, "0")}:00</b> med <b>${fmtDec(peakHourVal, 2)} kWh/t</b>${esc(peakInsightSub)}, mens bundniveauet ligger på ~${fmtDec(minHourVal, 2)} kWh/t.
              </div>` : ""}
              ${has("temperatures") ? `<div class="ins" data-section="ins-temp">
                <div class="ins-title">⚡ Returtemperatur &amp; Afkøling</div>
                Aktuelt års-snit er <b>${rtCur > 0 ? `${fmtDec(rtCur)} °C` : "–"}</b>${!allowBonus ? `${rtCur > 0 ? (rtCur <= penaltyT ? ` (🟢 under krav ≤<b>${penaltyT} °C</b> — intet gebyr)` : ` (<b>+${fmtDec(rtCur - penaltyT, 1)} °C</b> over krav <b>${penaltyT} °C</b>)`) : ` (krav: ≤<b>${penaltyT} °C</b>)`}${fwdTemp !== null ? ` ved fremløb <b>${fmtDec(fwdTemp)} °C</b>` : ""}` : (singleReturnTarget ? (rtCur > 0 ? (rtDist < 0 ? ` (🟢 under forventet retur <b>${bonusT} °C</b>)` : (rtCur > penaltyT ? ` (<b>+${fmtDec(rtCur - penaltyT, 1)} °C</b> over forventet retur <b>${penaltyT} °C</b>)` : ` (på forventet retur <b>${bonusT} °C</b>)`)) : ` (forventet retur: <b>${bonusT} °C</b>)`) : (rtCur > 0 ? (rtDist < 0 ? ` (🟢 i bonus-zone under <b>${bonusT} °C</b>)` : ` (<b>${fmtDec(rtDist, 1)} °C</b> fra bonus under <b>${bonusT} °C</b>, gebyr over <b>${penaltyT} °C</b>)`) : ` (bonus under <b>${bonusT} °C</b>, gebyr over <b>${penaltyT} °C</b>)`))}.
              </div>` : ""}
              ${hddEntries.length ? `<div class="ins">
                <div class="ins-title">📈 Effektivitet pr. graddag (kWh / HDD17)</div>
                ${esc(hddSummary)}
                <div class="hdd-row">
                  ${hddEntries.map(([y, v]) => `<span class="hdd-pill">${esc(y)}: ${fmtDec(v, 2)}</span>`).join("")}
                </div>
              </div>` : ""}
            </div>
            <div class="tip" id="tip">${esc(t.tip_hint)}</div>
          </div>`}
          <div class="float-tip" id="floatTip" role="tooltip" aria-hidden="true"></div>
        </div>
      `;

      const wrapEl = this.shadowRoot.getElementById("wrap");
      const tip = this.shadowRoot.getElementById("tip");
      const floatTip = this.shadowRoot.getElementById("floatTip");
      if (tip) {
        const positionFloat = (el) => {
          if (!floatTip || !wrapEl || typeof wrapEl.getBoundingClientRect !== "function" || typeof el.getBoundingClientRect !== "function") return;
          const wr = wrapEl.getBoundingClientRect();
          const er = el.getBoundingClientRect();
          if (!wr.width || !er.width) return;
          floatTip.textContent = el.dataset.tip || "";
          const rawX = er.left - wr.left + er.width / 2;
          const clampedX = Math.min(Math.max(120, rawX), Math.max(120, wr.width - 120));
          const topY = er.top - wr.top - 10;
          const flipBelow = topY < 38;
          floatTip.style.left = `${clampedX}px`;
          floatTip.style.top = `${flipBelow ? er.bottom - wr.top + 8 : topY}px`;
          floatTip.classList.toggle("below", flipBelow);
          floatTip.classList.add("on");
          floatTip.setAttribute("aria-hidden", "false");
        };
        const hideFloat = () => {
          if (!floatTip) return;
          floatTip.classList.remove("on");
          floatTip.setAttribute("aria-hidden", "true");
        };
        this.shadowRoot.querySelectorAll("[data-tip]").forEach((el) => {
          const show = () => { tip.textContent = el.dataset.tip; tip.classList.add("on"); positionFloat(el); };
          el.addEventListener("mouseenter", show);
          el.addEventListener("focus", show);
          el.addEventListener("mouseleave", hideFloat);
          el.addEventListener("blur", hideFloat);
          el.addEventListener("click", () => { tip.textContent = el.dataset.tip; tip.classList.add("on"); });
        });
      }

      const sel = this.shadowRoot.getElementById("utilSel");
      if (sel) {
        sel.addEventListener("change", (ev) => {
          this._selectedUtilId = ev.target.value;
          const chosen = UTILITIES.find((u) => u.id === this._selectedUtilId);
          if (chosen) {
            this._wizPortalUrl = chosen.url;
            this._wizLocation = chosen.city;
          }
          this._render();
        });
      }
      const loginBtn = this.shadowRoot.getElementById("loginBtn");
      if (loginBtn) {
        loginBtn.addEventListener("click", () => {
          const portalEl = this.shadowRoot.getElementById("portalUrlInput");
          const chosen = UTILITIES.find((u) => u.id === (this._selectedUtilId || activeUtilId));
          const url = portalEl?.value?.trim() || chosen?.url || activePortalUrl;
          if (/^https?:\/\//i.test(url)) window.open(url, "_blank", "noopener,noreferrer");
        });
      }
      const numOrNull = (id) => {
        const raw = this.shadowRoot.getElementById(id)?.value;
        if (raw === undefined || raw === null || String(raw).trim() === "") return null;
        const n = Number(raw);
        return Number.isFinite(n) ? n : null;
      };
      const readWizPayload = (startSync, completeSetup) => {
        const notifySelEl = this.shadowRoot.getElementById("notifySel");
        const notifyVal = notifySelEl && notifySelEl.value !== "__custom__"
          ? notifySelEl.value.trim()
          : (this.shadowRoot.getElementById("notifyInput")?.value?.trim() ?? notifySvc);
        const p = {
          utility_id: this._selectedUtilId || activeUtilId,
          portal_url: this.shadowRoot.getElementById("portalUrlInput")?.value?.trim() || wizPortalUrl,
          location_name: this.shadowRoot.getElementById("locInput")?.value?.trim() ?? wizLocation,
          bonus_temp: Number(this.shadowRoot.getElementById("bonusInput")?.value ?? wizBonus),
          penalty_temp: Number(this.shadowRoot.getElementById("penaltyInput")?.value ?? wizPenalty),
          notify_service: notifyVal,
          start_sync: startSync,
          complete_setup: completeSetup,
        };
        const priceVal = numOrNull("priceInput");
        if (priceVal !== null) p.price_dkk_per_kwh = priceVal;
        const motivVal = numOrNull("motivPctInput");
        if (motivVal !== null) p.motivation_pct_per_k = motivVal;
        const fixedM2Val = numOrNull("fixedM2Input");
        if (fixedM2Val !== null) p.fixed_fee_dkk_per_m2_year = fixedM2Val;
        const areaM2Val = numOrNull("areaM2Input");
        if (areaM2Val !== null) p.heated_area_m2 = areaM2Val;
        const fixedYearVal = numOrNull("fixedYearInput");
        if (fixedYearVal !== null) p.fixed_fee_dkk_per_year = fixedYearVal;
        const mu = this.shadowRoot.getElementById("mitidUserInput")?.value?.trim();
        if (mu) p.mitid_username = mu;
        return p;
      };
      const notifySel = this.shadowRoot.getElementById("notifySel");
      if (notifySel) {
        notifySel.addEventListener("change", (ev) => {
          if (ev.target.value === "__custom__") {
            this._wizNotifyCustom = true;
          } else {
            this._wizNotifyCustom = false;
            this._wizNotify = ev.target.value;
          }
          this._render();
        });
      }
      [
        ["mitidUserInput", "_wizMitidUser"],
        ["portalUrlInput", "_wizPortalUrl"],
        ["locInput", "_wizLocation"],
        ["bonusInput", "_wizBonus"],
        ["penaltyInput", "_wizPenalty"],
        ["priceInput", "_wizPrice"],
        ["motivPctInput", "_wizMotivPct"],
        ["fixedM2Input", "_wizFixedM2"],
        ["areaM2Input", "_wizAreaM2"],
        ["fixedYearInput", "_wizFixedYear"],
        ["efPriceInput", "_wizEfPrice"],
        ["efBonusInput", "_wizEfBonus"],
        ["efPenaltyInput", "_wizEfPenalty"],
        ["efMotivPctInput", "_wizEfMotivPct"],
        ["efForwardInput", "_wizEfForward"],
        ["efFixedM2Input", "_wizEfFixedM2"],
        ["efAreaM2Input", "_wizEfAreaM2"],
        ["efFixedYearInput", "_wizEfFixedYear"],
        ["notifyInput", "_wizNotify"],
      ].forEach(([id, prop]) => {
        const el = this.shadowRoot.getElementById(id);
        if (el) el.addEventListener("input", (e) => { this[prop] = e.target.value; });
      });
      const saveTariffBtn = this.shadowRoot.getElementById("saveTariffBtn");
      if (saveTariffBtn && this._hass) {
        saveTariffBtn.addEventListener("click", () => {
          const payload = { complete_setup: true };
          if (a.entry_id) payload.entry_id = a.entry_id;
          else if (activeUtilId) payload.utility_id = activeUtilId;
          const priceVal = numOrNull("efPriceInput");
          if (priceVal !== null) payload.price_dkk_per_kwh = priceVal;
          const motivVal = numOrNull("efMotivPctInput");
          if (motivVal !== null) payload.motivation_pct_per_k = motivVal;
          const bonusVal = numOrNull("efBonusInput");
          if (bonusVal !== null) payload.bonus_temp = bonusVal;
          const penaltyVal = numOrNull("efPenaltyInput");
          if (penaltyVal !== null && (penaltyVal > 0 || !allowBonus)) {
            payload.penalty_temp = penaltyVal;
          } else if (bonusVal !== null && bonusVal > 0) {
            payload.penalty_temp = bonusVal;
          }
          const fwdVal = numOrNull("efForwardInput");
          if (fwdVal !== null) payload.forward_temp = fwdVal;
          const fixedM2Val = numOrNull("efFixedM2Input");
          if (fixedM2Val !== null) payload.fixed_fee_dkk_per_m2_year = fixedM2Val;
          const areaM2Val = numOrNull("efAreaM2Input");
          if (areaM2Val !== null) payload.heated_area_m2 = areaM2Val;
          const fixedYearVal = numOrNull("efFixedYearInput");
          if (fixedYearVal !== null) payload.fixed_fee_dkk_per_year = fixedYearVal;
          this._setupOpen = false;
          this._hass.callService("kmd_easy_energy", "configure_utility", payload);
          this._render();
        });
      }
      const startMitidBtn = this.shadowRoot.getElementById("startMitidBtn");
      if (startMitidBtn && this._hass) {
        startMitidBtn.addEventListener("click", () => {
          if (this._startingSync) return;
          const typedUser = this.shadowRoot.getElementById("mitidUserInput")?.value?.trim();
          if (!typedUser && !hasMitidUser) {
            this._mitidErr = "Indtast dit MitID Bruger-ID ovenfor før du starter synkronisering.";
            this._render();
            return;
          }
          const payload = readWizPayload(true, false);
          this._wizMitidUser = "";
          this._mitidErr = "";
          this._startingSync = true;
          this._hass.callService("kmd_easy_energy", "configure_utility", payload);
          this._render();
          setTimeout(() => {
            this._startingSync = false;
            if (!this._mitidQr && !this._mitidOtp) this._render();
          }, 5000);
        });
      }
      const completeNowBtn = this.shadowRoot.getElementById("completeNowBtn");
      if (completeNowBtn && this._hass) {
        completeNowBtn.addEventListener("click", () => {
          this._setupOpen = false;
          this._hass.callService("kmd_easy_energy", "configure_utility", readWizPayload(false, true));
        });
      }
      const saveTokenBtn = this.shadowRoot.getElementById("saveTokenBtn");
      if (saveTokenBtn && this._hass) {
        saveTokenBtn.addEventListener("click", async () => {
          const tok = this.shadowRoot.getElementById("manualTokenInput")?.value?.trim();
          const cid = this.shadowRoot.getElementById("manualCustIdInput")?.value?.trim();
          if (!tok) return;
          this._setupOpen = false;
          await this._hass.callService("kmd_easy_energy", "configure_utility", readWizPayload(false, true));
          const payload = { access_token: tok };
          if (cid) payload.customer_id = cid;
          await this._hass.callService("kmd_easy_energy", "update_token", payload);
        });
      }
      const resetSetupBtn = this.shadowRoot.getElementById("resetSetupBtn");
      if (resetSetupBtn && this._hass) {
        resetSetupBtn.addEventListener("click", () => {
          this._setupOpen = false;
          this._hass.callService("kmd_easy_energy", "reset_setup", {});
        });
      }
      const triggerSync = () => {
        if (!this._hass) return;
        const payload = {};
        if (a.entry_id) payload.entry_id = a.entry_id;
        else if (activeUtilId) payload.utility_id = activeUtilId;
        const customBtn = cfg.sync_button_entity;
        if (customBtn && customBtn.startsWith("button.")) {
          this._hass.callService("button", "press", { entity_id: customBtn });
          return;
        }
        if (customBtn && customBtn.startsWith("input_button.")) {
          this._hass.callService("input_button", "press", { entity_id: customBtn });
          return;
        }
        // Prefer the domain sync service (looks up the entry by id / utility_id and
        // works for non-admin wall-tablet users across KMD, E|Forsyning, and Watts On).
        this._hass.callService("kmd_easy_energy", "sync", payload);
      };
      const efSyncBtn = this.shadowRoot.getElementById("efSyncBtn");
      if (efSyncBtn) efSyncBtn.addEventListener("click", triggerSync);
      const syncBtn = this.shadowRoot.getElementById("syncBtn");
      if (syncBtn) syncBtn.addEventListener("click", triggerSync);
      const syncTap = this.shadowRoot.getElementById("syncTap");
      if (syncTap) {
        syncTap.addEventListener("click", triggerSync);
        syncTap.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            triggerSync();
          }
        });
      }
      const onboardCard = this.shadowRoot.getElementById("onboardCard");
      if (onboardCard && showOnboarding && !isInitialSetup) {
        onboardCard.addEventListener("keydown", (ev) => {
          if (ev.key === "Escape") {
            ev.preventDefault();
            this._setupOpen = false;
            this._render();
          }
        });
      }
      ["efPriceInput", "efMotivPctInput", "efBonusInput", "efPenaltyInput", "efForwardInput"].forEach((id) => {
        const el = this.shadowRoot.getElementById(id);
        if (el && saveTariffBtn) {
          el.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter") { ev.preventDefault(); saveTariffBtn.click(); }
          });
        }
      });
      const mitidUserEl = this.shadowRoot.getElementById("mitidUserInput");
      if (mitidUserEl && startMitidBtn) {
        mitidUserEl.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") { ev.preventDefault(); startMitidBtn.click(); }
        });
      }
      const openSetupBtn = this.shadowRoot.getElementById("openSetupBtn");
      if (openSetupBtn) {
        openSetupBtn.addEventListener("click", () => { this._setupOpen = true; this._render(); });
      }
      const costHintSetupBtn = this.shadowRoot.getElementById("costHintSetupBtn");
      if (costHintSetupBtn) {
        costHintSetupBtn.addEventListener("click", () => { this._setupOpen = true; this._render(); });
      }
      const closeSetupBtn = this.shadowRoot.getElementById("closeSetupBtn");
      if (closeSetupBtn) {
        closeSetupBtn.addEventListener("click", () => { this._setupOpen = false; this._render(); });
      }
      const sanitizeIssueNote = (raw) => String(raw || "")
        .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, "[email]")
        .replace(/\b\d{6}-?\d{4}\b/g, "[id]")
        .replace(/\?[^\s)]+/g, "")
        .replace(/\b[A-Za-z0-9_-]{24,}\b/g, "[redacted]")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 220);
      const buildFeedbackBody = (kind) => {
        const listedUnits = Array.isArray(a.available_units)
          ? a.available_units.map((u) => u.Name).filter(Boolean)
          : [];
        const inferredUnits = [];
        if (!listedUnits.length) {
          if (yCur > 0 || yPrev > 0 || Object.keys(dy.days || {}).length > 0 || (Array.isArray(hr.kwh) && hr.kwh.length > 0) || has("hourly") || has("daily") || has("monthly")) inferredUnits.push("kWh");
          if (has("volume")) inferredUnits.push("m3");
          if (has("temperatures") || rtCur > 0) inferredUnits.push("°C");
        }
        const units = (listedUnits.length ? listedUnits : inferredUnits).join(", ")
          || (Array.isArray(a.available_units) ? "none" : "ukendt");
        const authMethodLabel = backend === "wattson"
          ? "Watts On (OAuth PKCE)"
          : backend === "eforsyning"
            ? "E|Forsyning (Forbrugernummer + webpinkode)"
            : "Pure-HA MitID (SRP + OIDC PKCE)";
        const integrationVer = a.integration_version ? String(a.integration_version) : "ukendt";
        const lines = [
          `### Utility Verification Report (${kind})`,
          `- **Utility ID:** \`${activeUtilId}\``,
          `- **Utility Name:** ${activeUtil.name}`,
          `- **Portal URL:** ${activePortalUrl}`,
          `- **Status:** ${kind}`,
          `- **Discovered Units:** ${units || "none"}`,
          `- **Direct Temp Unit:** ${Boolean(a.has_direct_temp)}`,
          `- **Auth Method:** ${authMethodLabel}`,
          `- **Card Version:** ${VER}`,
          `- **Integration Version:** ${integrationVer}`,
        ];
        if (kind === "Issue") {
          lines.push(`- **Sync State:** \`${a.sync_state || "idle"}\``);
          if (a.sync_message) {
            lines.push(`- **Last Sync Message:** ${sanitizeIssueNote(a.sync_message)}`);
          }
        }
        lines.push(
          ``,
          `_Sanitized report: contains no MitID ID, tokens, customer numbers, or consumption values._`,
        );
        return lines.join("\n");
      };
      const openGhFeedback = (kind) => {
        const title = encodeURIComponent(`[Utility ${kind}] ${activeUtil.name} (${activeUtilId})`);
        const body = encodeURIComponent(buildFeedbackBody(kind));
        const lbl = kind === "Confirmed" ? "utility-verification" : "bug";
        window.open(`https://github.com/DKAnord/fjernvarme-dk-ha/issues/new?labels=${lbl}&title=${title}&body=${body}`, "_blank", "noopener");
      };
      const copyFeedback = async () => {
        const txt = buildFeedbackBody(utilStatus === "confirmed" ? "Confirmed" : "Working");
        try { await navigator.clipboard.writeText(txt); } catch (_) { /* ignore */ }
        this._fbCopied = true;
        this._render();
        setTimeout(() => { this._fbCopied = false; this._render(); }, 3000);
      };
      ["fbGithubBtn", "obFbGithubBtn"].forEach((id) => {
        this.shadowRoot.getElementById(id)?.addEventListener("click", () => openGhFeedback("Confirmed"));
      });
      ["fbIssueBtn", "obFbIssueBtn"].forEach((id) => {
        this.shadowRoot.getElementById(id)?.addEventListener("click", () => openGhFeedback("Issue"));
      });
      ["fbCopyBtn", "obFbCopyBtn"].forEach((id) => {
        this.shadowRoot.getElementById(id)?.addEventListener("click", copyFeedback);
      });
    }
  }

  class KmdEasyEnergyCardEditor extends HTMLElement {
    setConfig(config) {
      this._config = { ...config };
      this._render();
    }
    set hass(hass) {
      this._hass = hass;
      if (!this._rendered) this._render();
    }
    _emit(patch) {
      const next = { ...this._config, ...patch };
      Object.keys(next).forEach((k) => { if (next[k] === undefined) delete next[k]; });
      this._config = next;
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
    }
    _render() {
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      this._rendered = true;
      const c = this._config || {};
      const utilOpts = UTILITIES.map((u) =>
        `<option value="${u.id}" ${c.utility_id === u.id ? "selected" : ""}>${u.status === "confirmed" ? "✅" : "🧪"} ${esc(u.name)}</option>`
      ).join("");
      this.shadowRoot.innerHTML = `
        <style>
          .ed { display: grid; gap: 10px; padding: 8px 0; font-family: inherit; }
          label { display: grid; gap: 4px; font-size: 12.5px; font-weight: 600; }
          input, select { padding: 8px; border-radius: 8px; border: 1px solid rgba(148,163,184,0.4); background: transparent; color: inherit; }
          .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
          .chk { display: flex; align-items: center; gap: 8px; }
        </style>
        <div class="ed">
          <label>Overview / Data Sensor
            <input id="entity" value="${esc(c.entity || "")}" placeholder="Auto-detect (*_overview / *_overblik or sensor.kredslob_varme)" />
          </label>
          <label>Utility Login Portal (Smart Dropdown)
            <select id="utility_id"><option value="">Auto from sensor</option>${utilOpts}</select>
          </label>
          <div class="row">
            <label>Language
              <select id="language">
                <option value="da" ${c.language !== "en" ? "selected" : ""}>Dansk</option>
                <option value="en" ${c.language === "en" ? "selected" : ""}>English</option>
              </select>
            </label>
            <label>City / Location Label
              <input id="location" value="${esc(c.location || "")}" placeholder="e.g. Aarhus" />
            </label>
          </div>
          <div class="row">
            <label>Return Bonus (°C, empty = auto)
              <input id="bonus_temp" type="number" step="0.5" value="${esc(c.bonus_temp ?? "")}" placeholder="Auto" />
            </label>
            <label>Return Penalty (°C, empty = auto)
              <input id="penalty_temp" type="number" step="0.5" value="${esc(c.penalty_temp ?? "")}" placeholder="Auto" />
            </label>
          </div>
          <label class="chk">
            <input id="show_sync_bar" type="checkbox" ${c.show_sync_bar !== false ? "checked" : ""} />
            Show top login &amp; sync bar
          </label>
        </div>
      `;
      ["entity", "utility_id", "language", "location"].forEach((id) => {
        this.shadowRoot.getElementById(id).addEventListener("change", (e) => this._emit({ [id]: e.target.value }));
      });
      ["bonus_temp", "penalty_temp"].forEach((id) => {
        this.shadowRoot.getElementById(id).addEventListener("change", (e) => {
          const raw = e.target.value.trim();
          this._emit({ [id]: raw === "" ? undefined : Number(raw) });
        });
      });
      this.shadowRoot.getElementById("show_sync_bar").addEventListener("change", (e) => this._emit({ show_sync_bar: e.target.checked }));
    }
  }

  if (!customElements.get("kmd-easy-energy-card")) {
    customElements.define("kmd-easy-energy-card", KmdEasyEnergyCard);
    customElements.define("kmd-easy-energy-card-editor", KmdEasyEnergyCardEditor);
    window.customCards = window.customCards || [];
    window.customCards.push({
      type: "kmd-easy-energy-card",
      name: "Dansk Fjernvarme: Dashboard",
      description: "Plug-and-play dansk fjernvarme-dashboard med 1-klik MitID-sync, smart værk-vælger og Open-Meteo vejrindsigter",
      preview: true,
      documentationURL: "https://github.com/DKAnord/fjernvarme-dk-ha",
    });
  }
  console.info(`%c KMD-EASY-ENERGY-CARD %c v${VER} `, "background:#ea580c;color:#fff;font-weight:700", "background:#0f172a;color:#fff");
})();

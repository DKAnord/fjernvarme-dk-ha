# 🔥 Fjernvarme (KMD Easy Energy) — HA Connector & Dashboard

Komplet, **100% lokal** Home Assistant-integration (`kmd_easy_energy`) og **Plug-and-Play Lovelace-dashboard** (`custom:kmd-easy-energy-card`) til danske fjernvarmeværker på **KMD Easy Energy** (`easy-energy-plugin-api.kmd.dk`).

Log ind med **MitID direkte i Home Assistant** i ren Python (OIDC PKCE + NemLog-in + MitID SRP) — **ingen Chromium, ingen ekstern server eller add-on** påkrævet. Kører direkte på Raspberry Pi, Home Assistant OS og Docker.

---

## ✨ Funktioner

- **🔐 100% indbygget MitID-login i Home Assistant:** Understøtter både **4-cifret engangskode** (vises direkte på dashboardet + valgfri push-notifikation) og **roterende QR-kode**. Dit MitID Bruger-ID gemmes kun lokalt i Home Assistants krypterede ConfigEntry.
- **🏭 Smart værk-vælger:** Vælg mellem bekræftede værker (`✅ Bekræftet`) og kandidater (`🧪 Afventer første test`), eller indtast en brugerdefineret portal-URL.
- **📊 Plug-and-Play Fjernvarme Dashboard (`custom:kmd-easy-energy-card`):**
  - **Førstegangsopsætning (Wizard):** Guider dig trin-for-trin igennem valg af værk, MitID Bruger-ID og første synkronisering.
  - **Daglig drift:** 1-klik sync-banner, **4 KPI-kort** (ÅTD forbrug, returtemperatur vs. bonus/gebyr, prognose mod budget, regninger & saldo), **5 interaktive SVG-grafer** (månedligt forbrug vs. sidste år + udetemp, returtemperatur, timeprofil, MTD vs. YTD, dagligt forbrug) og **4 Open-Meteo vejrindsigter** (R², grundlast, spidstime og kWh pr. graddag HDD17).
- **📣 Indbygget værk-feedback:** Testede du et nyt værk? Brug knappen **Bekræft på GitHub** direkte i kortet — den sender kun tekniske metadata (værk-ID og fundne målerenheder) uden persondata, MitID-ID, tokens eller forbrugstal.

---

## 🏭 Understøttede varmeværker

### ✅ Bekræftet (Testet live)
| Værk | By | Login-portal | Status |
|---|---|---|---|
| **Kredsløb** | Aarhus / Brabrand | https://minvarme.kredslob.dk/ | ✅ Bekræftet |

### 🧪 Afventer første test (Verificerede KMD / Min Forsyning-portaler)
| Værk | By | Login-portal | Status |
|---|---|---|---|
| **Galten Varmeværk** | Galten | https://minvarme.kredslob.dk/ | 🧪 Afventer 1. test |
| **Energi Ikast** | Ikast | https://energi-ikast.dk/ | 🧪 Afventer 1. test |
| **Struer Energi** | Struer | https://struerenergi.dk/selvbetjening/ | 🧪 Afventer 1. test |
| **Envafors / SK Forsyning** | Slagelse / Næstved / Sorø | https://skenergi.dk/minforsyning/ | 🧪 Afventer 1. test |
| **Frederikshavn Forsyning** | Frederikshavn | https://www.forsyningen.dk/selvbetjening | 🧪 Afventer 1. test |
| **Vestforsyning** | Holstebro | https://www.vestforsyning.dk/selvbetjening/ | 🧪 Afventer 1. test |
| **Bornholms Energi & Forsyning (BEOF)** | Bornholm | https://minforsyning.beof.dk/ | 🧪 Afventer 1. test |
| **Kalundborg Forsyning** | Kalundborg | https://kalfor.dk/selvbetjening/min-forsyning | 🧪 Afventer 1. test |
| **Albertslund Forsyning** | Albertslund | https://forsyning.albertslund.dk/selvbetjening | 🧪 Afventer 1. test |

### 🔎 Kandidater (KMD Easy Energy-kunder — afventer test)
- **Nykøbing Sjælland Varmeværk** · **Langeland Energi & Forsyning (LEF)** · **Forsyning Helsingør (Mit FH)** · **Provas (Haderslev)** · **Skanderborg Forsyning** · **SAMN Forsyning** · **go'energi** · samt *Brugerdefineret URL*

---

## 📦 Installation via HACS

1. Åbn **HACS** i Home Assistant → **Integrationer** → menuen (`⋮` øverst til højre) → **Brugerdefinerede arkiver (Custom repositories)**.
2. Tilføj:
   - **Repository:** `https://github.com/DKAnord/kmd-fjernvarme-ha`
   - **Kategori:** `Integration`
3. Søg efter **Fjernvarme (KMD)** i HACS, klik **Hent (Download)**, og genstart Home Assistant.
4. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration → Fjernvarme (KMD Easy Energy)**, og vælg dit varmeværk.
5. Tilføj dashboard-kortet som ressource under **Indstillinger → Dashboards → (`⋮`) Ressourcer → Tilføj ressource**:
   - **URL:** `/local/js/kmd-easy-energy-card.js`
   - **Ressourcetype:** `JavaScript-modul`
   *(Integrationen kopierer automatisk kortet til `/config/www/js/kmd-easy-energy-card.js` ved opstart).*
6. Tilføj kortet **Fjernvarme (KMD Easy Energy): Dashboard** på et dashboard via den visuelle kortvælger (eller se [dashboards/lovelace-plug-and-play.yaml](dashboards/lovelace-plug-and-play.yaml)).

---

## 🔑 Førstegangsopsætning & MitID-guide

### Sådan gør du (3 enkle trin)
1. Indtast dit **MitID Bruger-ID** i opsætningskortet på dashboardet *(gemmes kun lokalt i Home Assistant)*, og tryk på **🚀 Gem & Start MitID-synkronisering**. *(Åbn ikke selv værkets hjemmeside i browseren samtidig — det giver MitID-fejl `CAP008`).*
2. **Åbn straks MitID-appen på din telefon og lås den op** — MitID danner først engangskoden / QR-koden i det øjeblik, appen åbnes.
3. Aflæs de **4 cifre** direkte på dashboard-kortet (eller i push-notifikationen) — eller scan QR-koden — og godkend i MitID-appen!

> [!TIP]
> **4-cifret engangskode vs. QR-kode på telefonen**
> Når du starter synkroniseringen fra din telefon, kan du ikke scanne en QR-kode på samme skærm. I MitID-appen kan du skifte fra QR-kode til 4-cifrede engangskoder:
> **MitID-app → Menu (⚙️) → Godkend med QR- eller engangskoder → Engangskoder**.
> *Bemærk: MitID har af sikkerhedshensyn 24 timers ventetid ved første skift.*

---

## 🧩 Entiteter & Tjenester

### Sensorer & Knap (oprettes pr. værk)
- `sensor.<værk>_overview` — Årsforbrug (kWh) + komplette dashboard-attributter (`annual`, `monthly`, `daily`, `hourly`, `return_temp`, `weather`, `insights`, `forecast`, `billing`)
- `sensor.<værk>_energy` — Aktuel måneds forbrug (`kWh`)
- `sensor.<værk>_volume` — Volumen (`m³`, `device_class: water` — cirkulerende fjernvarmevand, ikke drikkevand)
- `sensor.<værk>_return_temperature` — Returtemperatur (`°C`)
- `sensor.<værk>_balance` — Saldo (`DKK`)
- `sensor.<værk>_heating_degree_days_7d` — 7-dages graddage (`HDD17`) fra Open-Meteo
- `button.<værk>_sync` — 1-klik knap til at starte MitID-synkronisering

### Tjenester (`services.yaml`)
- `kmd_easy_energy.configure_utility` — Konfigurer værk, lokation, retur-grænser, MitID Bruger-ID og start evt. sync
- `kmd_easy_energy.refresh` — Opdater data fra KMD API og Open-Meteo med det aktive token
- `kmd_easy_energy.update_token` — Opdater Bearer token manuelt eller via eksternt script
- `kmd_easy_energy.start_mitid_sync` — Start indbygget MitID-login (bruges af dashboard-kortet)
- `kmd_easy_energy.reset_setup` — Nulstil dashboardet til førstegangsopsætning

---

## 🔒 Privatliv & Sikkerhed

- Integrationen kommunikerer **kun direkte** mellem din Home Assistant-instans og KMD Easy Energy / NemLog-in / MitID / Open-Meteo.
- MitID Bruger-ID og access tokens lagres kun lokalt i Home Assistants `.storage/core.config_entries` (i klartekst i den krypterede HA-konfiguration — det er standard for config entries).
- Forbrugsdata caches i den private fil `.storage/kmd_easy_energy.<entry_id>` — **ikke** i `/local/` / `www/`.
- MitID-engangskode og QR vises midlertidigt i en notifikation og på dashboard-kortet. De gemmes **ikke** på sensorattributter og havner derfor ikke i historikken. Eventuelle push-beskeder har koden i *brødteksten*, aldrig i titlen.
- Når tokenet udløber (~45–60 min), beder Home Assistant om gen-login (indsæt token eller start MitID). Sensorerne bliver stående på sidste cachede værdier, hvis de findes.
- Den valgfrie feedback-knap til GitHub åbner kun en forudfyldt kladde i din browser uden personoplysninger, tokens, kundenumre eller forbrugstal.

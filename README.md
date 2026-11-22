# 🔥 Fjernvarme (KMD Easy Energy) — HA Connector & Dashboard

[![Åbn i HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DKAnord&repository=kmd-fjernvarme-ha&category=integration)

Komplet, **100% lokal** Home Assistant-integration (`kmd_easy_energy`) og **Plug-and-Play Lovelace-dashboard** (`custom:kmd-easy-energy-card`) til danske fjernvarmeværker på **KMD Easy Energy** (`easy-energy-plugin-api.kmd.dk`).

Log ind med **MitID direkte i Home Assistant** i ren Python (OIDC PKCE + NemLog-in + MitID SRP) — **ingen Chromium, ingen ekstern server eller add-on** påkrævet. Kører direkte på Raspberry Pi, Home Assistant OS og Docker.

> [!NOTE]
> **`v0.3.0` er stabil for KMD / Kredsløb.** Integrationen er testet live hos **Kredsløb**. De øvrige 16 KMD-værker og brugerdefineret portal-URL afventer stadig live-test. **E|Forsyning** (Hjørring Varmeforsyning) og **Watts On** (Aalborg Forsyning) er eksperimentelle og ikke afprøvet live. Alle tilbagemeldinger er guld værd — også *"det virker ikke hos mit værk"*. Brug feedback-knappen på kortet eller [opret et issue](https://github.com/DKAnord/kmd-fjernvarme-ha/issues) med navnet på dit værk.

---

## 📸 Screenshots & Demo

<p align="center">
  <img src="docs/screenshots/kmd-fjernvarme-demo.gif" alt="KMD Fjernvarme HA Demo (MitID QR, sync og grafer)" width="780" />
</p>

| Desktop-overblik (inkl. weekend-påmindelse) | MitID QR & Notifikations-dropdown | Mobil-grafer & Spidstime |
| :---: | :---: | :---: |
| <img src="docs/screenshots/kmd-fjernvarme-desktop-overview.png" alt="Desktop overblik" width="320" /> | <img src="docs/screenshots/kmd-fjernvarme-setup-mitid.png" alt="MitID QR opsætning" width="280" /> | <img src="docs/screenshots/kmd-fjernvarme-mobile-charts.png" alt="Mobil grafer" width="160" /> |

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

### 🧪 E|Forsyning (eksperimentel — beta-testere søges)
- **Hjørring Varmeforsyning** ([eforsyning.dk/hjvarme](https://eforsyning.dk/hjvarme)) · samt *Andet E|Forsyning-værk* (kræver værkets forsyningid)

Se [E|Forsyning-backend](#-eforsyning-backend-eksperimentel) nedenfor.

### 🧪 Watts On (eksperimentel — beta-tester fra Aalborg søges)
- **Aalborg Forsyning** (fjernvarme vist i Watts On-appen)

Se [Watts On-backend](#-watts-on-backend-aalborg-forsyning-eksperimentel) nedenfor. *Forsyning Helsingør* viser også fjernvarme i Watts On ([fh.dk/watts](https://www.fh.dk/watts)), men står her fortsat som KMD-værk og er ikke ændret.

---

## 📦 Installation via HACS

**Hurtig 1-klik-tilføjelse i HACS:**

[![Åbn i HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DKAnord&repository=kmd-fjernvarme-ha&category=integration)

Klik på knappen for at tilføje arkivet i HACS → klik **Hent (Download)** (seneste version) → genstart Home Assistant.

<details>
<summary>Eller tilføj manuelt i HACS</summary>

1. Åbn **HACS** i Home Assistant → **Integrationer** → menuen (`⋮` øverst til højre) → **Brugerdefinerede arkiver (Custom repositories)**.
2. Tilføj:
   - **Repository:** `https://github.com/DKAnord/kmd-fjernvarme-ha`
   - **Kategori:** `Integration`
3. Søg efter **Fjernvarme (KMD)** i HACS, klik **Hent (Download)** (seneste version), og genstart Home Assistant.

</details>

**Efter genstart:**

1. Tilføj integrationen i Home Assistant (**Indstillinger → Enheder og tjenester → Tilføj integration → Fjernvarme (KMD Easy Energy)**) og vælg dit varmeværk:

   [![Tilføj integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=kmd_easy_energy)

2. Tilføj dashboard-kortet som ressource under **Indstillinger → Dashboards → (`⋮`) Ressourcer → Tilføj ressource**:
   - **URL:** `/local/js/kmd-easy-energy-card.js`
   - **Ressourcetype:** `JavaScript-modul`
   *(Integrationen kopierer automatisk kortet til `/config/www/js/kmd-easy-energy-card.js` ved opstart).*
3. Tilføj kortet **Fjernvarme (KMD Easy Energy): Dashboard** på et dashboard via den visuelle kortvælger (eller se [dashboards/lovelace-plug-and-play.yaml](dashboards/lovelace-plug-and-play.yaml)).

---

## 🔄 Sådan synkroniserer integrationen (session-baseret)

KMD udsteder kun en adgang (access token), der gælder ca. 1 time, og ingen refresh token. Derfor:

- **Hvert tryk på 🔄 Synkroniser er ét MitID-login.** Integrationen henter alt siden sidste synkronisering (inkl. timedata til Energy-dashboardet) og **kasserer adgangen straks**. Den gemmes ikke i konfigurationen eller cachen.
- **Ingen baggrundshentning:** Integrationen kontakter ikke KMD af sig selv. Sensorerne viser de senest hentede tal, og `sensor.<værk>_last_synced` (**Sidst synkroniseret**) viser hvornår. Efter en genstart af Home Assistant indlæses tallene fra den lokale cache uden at kontakte KMD.
- **Ingen "log ind igen"-reparationer:** Et udløbet token er normalt og giver ingen fejl. Kun et login, der reelt fejler, vises som fejl på kortet.
- **Første synkronisering** henter op til et års timehistorik. Senere synkroniseringer henter fra sidste synkronisering og frem (og eventuelle manglende måneder). Flere synkroniseringer samme dag er fine — Energy-statistikken skrives pr. time og bliver ikke dobbelt.
- **Blød påmindelse i weekenden:** Lørdag og søndag viser kortet en lille, rolig info-linje lige under Synkroniser-knappen — fx *"💧 Det er 4 dage siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik."* — hvis der ikke er synkroniseret torsdag, fredag eller lørdag samme uge (en synkronisering søndag fjerner den også). Mandag–fredag vises ingen påmindelse. Det er et venligt puf, ikke en fejl: ingen rød/advarsels-styling, ingen persistent notification, ingen reparation (repair) og ingen push. `binary_sensor.<værk>_sync_reminder` kan bruges i egne automatiseringer, og påmindelsen kan slås fra under integrationens indstillinger.

---

## 🧪 E|Forsyning-backend (eksperimentel)

> [!WARNING]
> E|Forsyning-understøttelsen er **ikke testet live** endnu. Har du fjernvarme fra et E|Forsyning-værk (fx Hjørring Varmeforsyning), så hjælp gerne som beta-tester og meld tilbage i et GitHub-issue — uden persondata.

Nogle værker bruger ikke KMD Easy Energy men **E|Forsyning** (eforsyning.dk / DFF-EDB). For dem bruger integrationen en anden backend, men **samme kort, sensorer, Energy-statistik og påmindelse**:

- **Login uden MitID:** Vælg værket under *Tilføj integration* og indtast **forbrugernummer** og **webpinkode** fra din varmeregning. De gemmes i Home Assistant som andre integrationers adgangskoder, logges aldrig og redigeres i diagnostics. Har kontoen flere installationer, vælger du én.
- **Automatisk daglig synkronisering** (standard kl. ca. 06:17, kan ændres eller slås fra under indstillinger). Knappen **Synkroniser nu** virker også. Weekend-påmindelsen er derfor slået fra som standard (kan slås til).
- **Data er daglige aflæsninger** (kWh, m³, frem- og returtemperatur) — ikke timedata. Energy-statistikken (`kmd_easy_energy:energy_<entry_id>` / `:volume_<entry_id>`) får én række pr. døgn (ved midnat), så døgntallene er rigtige, men der er ingen timeprofil.
- **Kortet viser kun det, der er data til:** ingen timeprofil, ingen saldo/regning og ingen budgetprognose for E|Forsyning, og ingen MitID-felter. Der står *Data fra E|Forsyning* under banneret.
- **Årstal** vises kun, når historikken dækker hele året (første synkronisering henter indeværende og forrige afregningsår), så du ser hellere "intet tal" end et forkert tal.
- **Andet E|Forsyning-værk:** Vælg *Andet E|Forsyning-værk* og indtast værkets **forsyningid**: åbn værkets side på eforsyning.dk, tryk F12 → *Netværk*, søg efter `GetVaerkSettings`, og kopiér værdien efter `forsyningid=`. Hjørring Varmeforsyning er forudfyldt (`B30A6948-2461-4827-B8EB-5D93169CCB8B`, fundet på den offentlige side).

**Tak til [kpoppel/homeassistant-eforsyning](https://github.com/kpoppel/homeassistant-eforsyning)** (Apache-2.0): Login- og dataprotokollen er studeret fra det projekt og genimplementeret som en asynkron klient (`api/eforsyning_client.py`, markeret som afledt værk med ændringer). Se [NOTICE](NOTICE) og licensteksten i `custom_components/kmd_easy_energy/api/LICENSE-eforsyning-Apache-2.0.txt`. Bruger du kun E|Forsyning og vil have flere detaljer (fx regningslinjer), så kig også på kpoppels integration.

---

## 🧪 Watts On-backend (Aalborg Forsyning, eksperimentel)

> [!WARNING]
> **Ikke testet live og uofficiel.** Watts On har ingen offentlig API eller dokumenterede API-vilkår, som vi har kunnet finde. Integrationen bruger samme API som Watts On-appen og kan holde op med at virke, hvis Watts ændrer den. Watts' generelle vilkår forbyder bl.a. reverse engineering af Watts' teknologi *i kommerciel henseende* — denne integration er et ikke-kommercielt hobbyprojekt, der kun henter **dine egne** forbrugsdata med **din egen** login, ca. én gang i døgnet. Brug den på eget ansvar. Er du beta-tester fra Aalborg, så meld gerne tilbage i et GitHub-issue (uden persondata — diagnostics viser kun feltnavne og endpoint-status).

Aalborg Forsyning bruger ikke KMD-portalen, men viser fjernvarme i **Watts On**-appen (Watts A/S). Backenden er bygget med [TheRealBatBro/Home-Assistant-Novafos-V2](https://github.com/TheRealBatBro/Home-Assistant-Novafos-V2) som inspiration (Novafos-**vand** via Watts On, MIT-licens) — tak til TheRealBatBro! Login-flowet, API-adressen og vandets felt-/endpointnavne er lært derfra og genimplementeret; se [NOTICE](NOTICE) og `custom_components/kmd_easy_energy/api/LICENSE-novafos-v2-MIT.txt`.

**Hvad er verificeret, og hvad er gættet?**
- ✅ *Verificeret i Novafos-V2 (for vand):* login via Watts' Azure AD B2C-app-registrering (PKCE, `msauth://`-redirect), refresh token der **roteres** ved hver fornyelse, API på `p.watts-energy.dk`, `users/api/v3/User`, lokationer/enheder, timedata med felterne `sd`/`ed`/`vol`/`mq` (`vol` er m³, selv om måleren siger liter; `-1` = ingen data; kun `mq = Measured` bruges).
- ❓ *Gættet for fjernvarme (skal bekræftes af en beta-tester):* hvilken adresse varmedata ligger på (vi prøver `heating/…`, `districtheating/…` og `heat/…` efter samme mønster som vand), feltnavne for energi og frem-/returtemperatur, enheden (kWh/MWh/GJ — Watts nævner alle tre for varme), og hvordan varmemåleren genkendes (`utilityType` med "heat"/"varme").
- Det, vi ikke genkender, bliver **ikke vist**: ingen gættede tal. Kortet og sensorerne viser kun det, der faktisk blev fundet (kapabiliteter), og diagnostics viser feltnavnene (ikke værdierne), så vi kan rette mappingen.

**Opsætning (uden MitID, uden at Home Assistant ser din Watts-adgangskode):**
1. Varmemåleren skal være tilføjet i Watts On-appen (kundenummer + måleradgangskode fra *Mit Aalborg Forsyning*).
2. *Tilføj integration → Fjernvarme → Aalborg Forsyning — Watts On (eksperimentel)*. Gør det på en **computer**.
3. Klik på login-linket og log ind med din Watts On-konto. Til sidst prøver browseren at åbne en `msauth://com.seasnve.watts/…`-adresse og fejler — det er forventet (Watts tillader kun appens egen adresse).
4. Kopiér adressen: Chrome/Edge: F12 → *Console* → linjen *"Failed to launch 'msauth://…'"* (eller F12 → *Network* → sidste anmodning → *Location*). Firefox: adresselinjen/fejlsiden. Indsæt den i feltet inden for ca. 10 minutter (koden virker kun én gang).
5. Home Assistant gemmer kun et **refresh token** i config entry (som andre integrationers adgangskoder). Det fornyes og gemmes ved hver synkronisering, logges aldrig og redigeres i diagnostics. Avanceret: har du allerede et token (fx fra `tools/login.py` i Novafos-V2), kan det indsættes i stedet.

**Drift:**
- **Automatisk daglig synkronisering** (ca. kl. 06:17, kan ændres/slås fra). Første gang hentes timedata fra 1. januar, derefter fra to døgn før seneste time (så sene rettelser kommer med). Weekend-påmindelsen er slået fra som standard.
- Hvor længe login holder uden synkronisering, bestemmer Watts (overview-attributten `login_expires_at` viser det, hvis Watts oplyser det). Udløber login, viser kortet en rolig besked: vælg **Genkonfigurer** på integrationen og log ind igen (ingen reparation/push).
- Timedata → Energy-statistik pr. time, timeprofil og døgn-/måneds-/årstal (årstal kun ved fuld dækning). Ingen saldo/regning eller budgetprognose.
- Indstillinger (avanceret): *energienhed* (auto/kWh/MWh/GJ) hvis tallene er 1000× forkerte, og en *endpoint-skabelon* (fx `heating/api/consumptions/<device_id>`), hvis en beta-tester finder den rigtige adresse.
- Aalborg Forsyning har også en officiel, betalt måler-API til **erhvervskunder** ([datadeling](https://aalborgforsyning.dk/services/forbrug/datadeling-for-fjernaflaeste-maalere/)); den bruges ikke her.

---

## 🔑 Førstegangsopsætning & MitID-guide

Gælder KMD-værker med MitID (fx Kredsløb). E|Forsyning og Watts On har deres egne trin under de respektive afsnit.

### Sådan gør du
1. **Installér via HACS** (seneste version) og genstart Home Assistant — se [Installation via HACS](#-installation-via-hacs).
2. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration → Fjernvarme (KMD Easy Energy)**, vælg dit værk, udfyld **MitID Bruger-ID** *(gemmes kun lokalt i Home Assistant)*, og tryk **Submit**. *Det opretter kun integrationen — der sker endnu intet MitID-login i denne dialog.*
3. Tilføj kort-ressourcen og kortet **Fjernvarme (KMD Easy Energy): Dashboard** på et dashboard — se trinene under [Installation via HACS](#-installation-via-hacs) (*Efter genstart*).
4. På kortet trykker du **🚀 Gem & Start MitID-synkronisering**. **Åbn straks MitID-appen på din telefon og lås den op** — MitID danner først QR-koden / engangskoden i det øjeblik, appen åbnes. *(Åbn ikke selv værkets hjemmeside i browseren samtidig — det giver MitID-fejl `CAP008`.)*
   - **Opsætter du på en tablet eller computer:** scan QR-koden på dashboard-kortet med MitID-appen på telefonen, og godkend.
   - **Opsætter du på samme telefon som MitID-appen:** indtast de **4 cifre** fra kortet (eller push-notifikationen) i MitID-appen, og godkend — det kræver, at engangskoder er slået til (se nedenfor).

> [!IMPORTANT]
> Ser du en dialog med **"Login & Token"** og et **Access token**-felt, kører du en gammel version (v0.2.0) – opdater i HACS.

> [!TIP]
> **Kun hvis du opsætter på samme telefon som MitID-appen: slå 4-cifret engangskode til**
> Bruger du en tablet eller computer til opsætningen og har MitID-appen på telefonen, skal du ikke ændre noget — scan blot QR-koden på kortet.
> Står kortet derimod på samme telefon som MitID-appen, kan QR-koden ikke scannes. Skift derfor fra QR-kode til 4-cifrede engangskoder i MitID-appen:
> **MitID-app → Menu (⚙️) → Godkend med QR- eller engangskoder → Engangskoder**.
> *Bemærk: MitID har af sikkerhedshensyn 24 timers ventetid ved første skift fra QR-kode til engangskode, hvorefter du bekræfter skiftet i appen.*

---

## 🧩 Entiteter & Tjenester

### Sensorer & Knap (oprettes pr. værk)
- `sensor.<værk>_overview` — Årsforbrug (kWh) + komplette dashboard-attributter (`annual`, `monthly`, `daily`, `hourly`, `return_temp`, `weather`, `insights`, `forecast`, `billing`)
- `sensor.<værk>_energy` — Aktuel måneds forbrug (`kWh`)
- `sensor.<værk>_volume` — Volumen (`m³`, `device_class: water` — cirkulerende fjernvarmevand, ikke drikkevand)
- `sensor.<værk>_return_temperature` — Returtemperatur (`°C`)
- `sensor.<værk>_balance` — Saldo (`DKK`)
- `sensor.<værk>_heating_degree_days_7d` — 7-dages graddage (`HDD17`) fra din udetemperatursensor og/eller Open-Meteo
- `sensor.<værk>_energy_price` — Variabel varmepris (`DKK/kWh`), fra indstillinger eller offentliggjort takst
- `sensor.<værk>_motivation_status` — Motivationstarif (`bonus` / `neutral` / `gebyr`) ud fra returtemperatur
- `sensor.<værk>_motivation_adjustment` — Motivationsregulering (`DKK/kWh`, negativ = bonus)
- `sensor.<værk>_kwh_per_hdd` — kWh pr. graddag (HDD17)
- `sensor.<værk>_normalized_annual_energy` — Normalår-korrigeret årsforbrug (kWh)
- `sensor.<værk>_forecast_annual_energy` — Årsprognose (ÅTD + resterende normalår-HDD × kWh/HDD)
- `binary_sensor.<værk>_motivation_penalty` — Til, når returtemperaturen er i gebyrzonen
- `binary_sensor.<værk>_abnormal_consumption` — Til ved unormalt døgnforbrug (samme ugedag, HDD-justeret). Ingen automatisk notifikation.
- `sensor.<værk>_last_synced` — **Sidst synkroniseret** (tidsstempel for seneste MitID-synkronisering)
- `binary_sensor.<værk>_sync_reminder` — Blød weekend-påmindelse (til lør/søn uden synkronisering tors–lør). Attributter: `message` (venlig tekst), `short` (*"Ikke synkroniseret i X dage"*), `days_since_sync`, `last_sync`, `enabled`.
- `button.<værk>_sync` — 1-klik knap til at starte MitID-synkronisering (E|Forsyning / Watts On: **Synkroniser nu**)

**Kun det, backenden kan levere:** Sensorer oprettes efter backendens evner (`capabilities`). E|Forsyning får fx ingen saldo-sensor. For Watts On oprettes volumen- og returtemperatur-sensorer først, når en synkronisering faktisk har fundet de data (integrationen genindlæses én gang). Overbliks-sensoren har attributterne `backend`, `data_source`, `data_granularity`, `capabilities` (hvad der faktisk er data til, fx `hourly`, `daily`, `monthly`, `temperatures`, `volume`, `cost`, `billing`, `forecast`, `mitid`, `reminder`) og `backend_capabilities`, og kortet skjuler grafer og felter uden data.

### Tjenester (`services.yaml`)
- `kmd_easy_energy.configure_utility` — Konfigurer værk, lokation, retur-grænser, MitID Bruger-ID og start evt. sync
- `kmd_easy_energy.refresh` — Genindlæs cachede data og genberegn afledte værdier (kontakter **ikke** KMD)
- `kmd_easy_energy.update_token` — Avanceret: kør én synkronisering med et token, du selv har hentet (tokenet gemmes ikke)
- `kmd_easy_energy.start_mitid_sync` — Start indbygget MitID-login (bruges af dashboard-kortet)
- `kmd_easy_energy.sync` — Synkroniser nu, uanset backend (MitID for KMD-værker, forbrugernummer-login for E|Forsyning, gemt Watts On-login for Aalborg Forsyning)
- `kmd_easy_energy.reset_setup` — Nulstil dashboardet til førstegangsopsætning

---

## ⚡ Energy-dashboard, priser og danske indsigter

- **Timehistorik til Energy-dashboardet:** Integrationen importerer eksterne statistikker `kmd_easy_energy:energy_<entry_id>` (kWh) og `kmd_easy_energy:volume_<entry_id>` (m³). Tilføj **disse** under Indstillinger → Dashboards → Energi — ikke måned-til-dato-sensorerne `sensor.*_energy` / `sensor.*_overview`, som nulstilles hver måned.
- Første synkronisering henter op til 12 måneders timehistorik; senere synkroniseringer udfylder data siden sidste synkronisering og op til tre manglende måneder ad gangen.
- **Varmepris:** Indstillinger → integrationen → Valgfrit: kr./kWh, ev. kr./m³, motivationstarif (kr./kWh/°C) og normalår-graddage. For **Kredsløb** udfyldes kWh-pris og motivation automatisk fra den offentliggjorte takst for kalenderåret ([prisside](https://www.kredslob.dk/privat/fjernvarme/fjernvarmepriser)). Sæt 0 for at bruge standarden. Andre værker har ingen indbygget pris — den skal tastes. Kredsløb afregner varme i kWh, så m³-pris er ikke udfyldt på forhånd.
- **Motivationstarif / afkøling:** Bonus under 30 °C, gebyr over 40 °C (kan ændres). Sensorerne viser status og kr./kWh-regulering.
- **Graddage og prognose:** kWh/HDD og et skønnet normalår (standard 3100 HDD17, kan ændres — det er *ikke* et officielt DMI 1991–2020-tal). Årsprognosen er ÅTD plus resterende skønnede graddage.
- **Unormalt forbrug:** `binary_sensor` slår til, hvis sidste komplette døgn ligger væsentligt over samme ugedag de foregående uger, også efter HDD-justering. Du bestemmer selv, om den skal styre en notifikation.

### 🌡️ Udetemperatur: egen sensor eller Open-Meteo

Graddage (HDD17), kWh pr. graddag, R², prognosen og temperaturkurverne på kortet bygger på døgnmiddel-udetemperatur. Du vælger kilden under **Indstillinger → Enheder & tjenester → integrationen → Konfigurer**:

1. **Egen udetemperatursensor i Home Assistant (anbefalet, lokal først).** Vælg en `sensor` med `device_class: temperature`. Døgnmidlet læses fra recorderens **langtidsstatistik** (timemiddel), så sensoren skal have `state_class: measurement` (det har de fleste vejrstationer og termometre). Integrationen læser kun, den skriver intet ekstra til databasen, og °F omregnes til °C. Et døgn tæller kun med fra sensoren, hvis der er statistik for mindst 18 af døgnets timer (i dag: mindst 6 timer for 7-dages graddagene).
2. **Open-Meteo** (ekstern, gratis vejrtjeneste) bruges for alle dage, sensoren ikke dækker, fx historik fra før sensoren blev sat op, eller hvis du ikke har valgt nogen sensor. Open-Meteo kaldes kun for de manglende dage. Dækker sensoren alt, kaldes Open-Meteo slet ikke. Placeringen vælges i denne rækkefølge:
   - **Egen placering**: bredde- og længdegrad i indstillingerne (lad felterne stå tomme, hvis du ikke har brug for det).
   - **Home Assistants hjemmelokation** (Indstillinger → System → Generelt). Det er standarden.
   - **Værkets placering** fra `utilities.json`. Den bruges kun, hvis Home Assistant ikke har en hjemmelokation (0/0).

Kortet viser kilden diskret, fx *Udetemp: Udetermometer*, *Udetemp: Open-Meteo (HA-hjemmelokation)*, *Udetemp: Open-Meteo (værkets placering)* eller ved blandede kilder *Udetemp: Udetermometer fra 5. mar 2026; dage uden sensorstatistik: Open-Meteo (HA-hjemmelokation)*. Overblikssensoren har de samme oplysninger i attributterne `temp_source` (`ha_sensor` / `open_meteo_home` / `open_meteo_utility` / `open_meteo_custom` / `mixed`) og `outdoor_temp` (sensor, antal dage pr. kilde, *slags* placering). Koordinater vises aldrig og redigeres i diagnostics. Attributterne gemmes ikke i recorderen. Ændrer du kilden, genberegnes temperaturerne med det samme, uden kontakt til værket.

**Opgradering (config entry 1.3):** Tidligere blev værkets koordinater kopieret ind som "din" placering, så Home Assistants hjemmelokation reelt aldrig blev brugt. Nu gemmes de kun som værksdata, og eksisterende installationer bruger automatisk HA-hjemmelokationen. Har du selv tastet andre koordinater i indstillingerne, beholdes de som egen placering. Koordinater, der blot var forudfyldt af den gamle formular (værkets placering, HA-hjemmelokationen eller standardværdien 56.15/10.10), fjernes.

Download diagnostics fra integrationen, hvis du skal have support: tokens, MitID-id, kunde-/måler-id, GPS-koordinater, push-service og adresser er redigeret.

---

## 🇬🇧 English notes (new in `v0.3.0`)

This is a Denmark-only Home Assistant integration for district heating on the KMD Easy Energy platform. Version **`v0.3.0`** moves the usage cache to private `.storage`, keeps MitID OTP/QR off sensor attributes and off the event bus (the bundled card gets them via the websocket subscription `kmd_easy_energy/mitid/subscribe`; event `kmd_easy_energy_mitid_challenge` carries status only), and uses **session-based sync**: KMD only issues a ~1 h access token (no refresh token), so each "Synkroniser" press is one MitID login that fetches everything since the last sync and then discards the token (never stored). There is no background polling, no reauth/repair for an expired token, and cached values are restored after an HA restart without contacting KMD. A soft, non-invasive weekend nudge (a calm info chip under the Synkroniser button; no notification, repair or push) (`binary_sensor.<entry>_sync_reminder`, Danish text on the card) is shown on Saturday/Sunday if there was no sync on Thursday, Friday or Saturday that week; it can be turned off in the options.

For the Energy dashboard, add the imported hourly statistics `kmd_easy_energy:energy_<entry>` / `:volume_<entry>`, not the month-to-date entities. Heat price (DKK/kWh) is an option; Kredsløb defaults come from the [official price page](https://www.kredslob.dk/privat/fjernvarme/fjernvarmepriser) for the current year. Motivation tariff, degree-day forecast and an abnormal-consumption binary sensor are included; the integration never sends leak notifications on its own.

**E|Forsyning (experimental, untested, beta testers wanted):** utilities on eforsyning.dk (e.g. Hjørring Varmeforsyning) use a second backend with consumer number + web PIN (no MitID), automatic daily sync, daily readings (no hourly data) and the same card/sensors/statistics. The card and the entities are capability-driven, so sections without data are hidden. The protocol was studied from and reimplemented after [kpoppel/homeassistant-eforsyning](https://github.com/kpoppel/homeassistant-eforsyning) (Apache-2.0) — thank you! See NOTICE.

**Watts On / Aalborg Forsyning (experimental, untested, unofficial — beta tester wanted):** a third backend reads district heating from the Watts On app backend, inspired by [TheRealBatBro/Home-Assistant-Novafos-V2](https://github.com/TheRealBatBro/Home-Assistant-Novafos-V2) (Novafos water via Watts On, MIT) — thank you! Login happens in your browser (paste the final `msauth://` redirect into the config flow); only a rotating refresh token is stored (redacted in diagnostics, never logged). The heat endpoint and heat field names are unverified guesses; whatever is not recognised is hidden rather than guessed. Watts On has no public API terms; use at your own risk.

**Outdoor temperature:** degree days and temperature lines use, in this order, an optional HA outdoor temperature sensor (daily means from the recorder's long-term statistics, local-first, read-only), then Open-Meteo (external service) for any day the sensor doesn't cover. Open-Meteo uses the location override from the options if set, otherwise the HA home location, otherwise the utility's coordinates. Config entry 1.3 stops treating the utility's coordinates as your location; explicit overrides are kept. The source is exposed as `temp_source` / `outdoor_temp` (no coordinates) and shown on the card.

**Breaking for custom dashboards:** attributes `mitid_otp_code` and `mitid_qr_svg` are removed. Use the bundled card or the websocket subscription above. Setup from a tablet/PC works with MitID's default QR (both animated frames are shown on the card); only setup on the same phone as the MitID app needs one-time codes enabled in the MitID app. Phone OTP sync is verified live on Kredsløb; tablet QR and additional KMD Easy Energy utilities are open for beta testing.

---

## 🔒 Privatliv & Sikkerhed

- Integrationen kommunikerer **kun direkte** mellem din Home Assistant-instans og KMD Easy Energy / NemLog-in / MitID / Open-Meteo (E|Forsyning-værker: eforsyning.dk og værkets DFF-EDB-server; Aalborg Forsyning: Watts On, `wattsenergyassistant.b2clogin.com` og `p.watts-energy.dk`). Open-Meteo får kun koordinater (egen placering, HA-hjemmelokation eller værkets placering) og kun for dage, din egen udetemperatursensor ikke dækker.
- E|Forsyning: forbrugernummer og webpinkode gemmes i `.storage/core.config_entries` (som andre HA-integrationers adgangskoder), logges aldrig og redigeres i diagnostics. Installationens adresse og målernummer gemmes ikke i cachen.
- MitID Bruger-ID lagres kun lokalt i Home Assistants `.storage/core.config_entries`. **Access tokens gemmes ikke**: de bruges til én synkronisering og kasseres. Et token fra en ældre version fjernes automatisk ved opgradering (config entry 1.2).
- Forbrugsdata caches i den private fil `.storage/kmd_easy_energy.<entry_id>` — **ikke** i `/local/` / `www/`.
- MitID-engangskode og QR vises midlertidigt på dashboard-kortet (via integrationens egen websocket-abonnement `kmd_easy_energy/mitid/subscribe`) og i en HA-notifikation. De gemmes **ikke** på sensorattributter eller i hændelser på event-bussen og havner derfor ikke i historikken/recorder-databasen. Eventet `kmd_easy_energy_mitid_challenge` indeholder kun status (`sync_state`, `has_otp`, `has_qr`).
- Vælger du en mobil push-service, sendes engangskoden i push-beskedens *brødtekst* (aldrig i titlen). Bemærk, at Home Assistant registrerer alle tjenestekald (`call_service`) i recorderen, så koden i en push-besked kan stå i databasen, indtil den ryddes. Koden er kun gyldig i den ene login-session. Vil du helt undgå det, så lad push-feltet stå tomt og aflæs koden på kortet.
- KMD-værker: Integrationen henter kun data, når du trykker **Synkroniser**. E|Forsyning- og Watts On-værker hentes desuden automatisk én gang i døgnet (kan slås fra).
- Watts On: Kun et refresh token gemmes i `.storage/core.config_entries` (din Watts-adgangskode ses aldrig af Home Assistant). Det roteres ved hver synkronisering, logges aldrig og redigeres i diagnostics sammen med bruger- og måler-id. Adresser, navne og målernumre fra Watts gemmes ikke. Ellers står sensorerne på de senest hentede værdier fra den lokale cache.
- Den valgfrie feedback-knap til GitHub åbner kun en forudfyldt kladde i din browser uden personoplysninger, tokens, kundenumre eller forbrugstal.
- **Diagnostics** (Indstillinger → integrationen → Download diagnostics) redigerer access tokens, MitID-brugernavn, kunde- og måler-id'er, GPS-koordinater, push-service og adresser. Store forbrugsserier er kun talt, ikke inkluderet.

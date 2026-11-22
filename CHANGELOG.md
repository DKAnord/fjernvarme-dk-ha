# Changelog

Alle væsentlige ændringer i **Fjernvarme (KMD Easy Energy) – HA Connector & Dashboard** dokumenteres her.

## [0.3.4] - 2026-11-22

### Omkostningsestimater & Dashboard (alle udbydere)
- **4 nye udbyder-uafhængige kr.-estimatsensorer** (`Effektiv varmepris`, `Estimeret forbrug (seneste døgn)`, `Estimeret forbrug (denne måned)`, `Estimeret forbrug (i år)` med `monthly_dkk`-attribut) — virker på tværs af KMD, Watts On og E|Forsyning, når varmepris er kendt eller indtastet under integrationens indstillinger.
- **Nyt `💰 Estimeret forbrug i kr.`-panel på dashboard-kortet:** Viser estimat for seneste døgn, denne måned, i år samt effektiv kr/kWh inkl. bonus/gebyr (ekskl. faste afgifter) og `~kr.` i månedsgrafens tooltips — inspireret af [@dkvand](https://github.com/dkvand)s dashboard.
- **Procentbaseret motivationstarif** (`motivation_pct_per_k`) i `tariff.py`, så fx ±2 %/°C automatisk skalerer med den valgte varmepris.
- **Kortets indbyggede værkliste** er synkroniseret med `utilities.json` (Aalborg `confirmed`, Helsingør/Fyn/Hillerød på Watts On), og misvisende `0 kWh` for forrige år uden data skjules.

## [0.3.3] - 2026-11-22

### Watts On
- **Aalborg Forsyning** er markeret som ✅ bekræftet live — stor tak til [@dkvand](https://github.com/dkvand) for live-test, sparring og PR #9 (varme-endpoint og felter `En` / `Vol` / `TI`/`TO` verificeret i v0.3.2).
- Nye Watts On-værker i værk-vælgeren, alle 🧪 afventer første test (beta-testere søges): **Forsyning Helsingør**, **Fjernvarme Fyn** og **Hillerød Forsyning**. Portalerne er verificeret mod Watts' officielle support og værkernes egne sider. Varmemåleren skal først parres i Watts On-appen.
- **Forsyning Helsingør** er skiftet fra KMD-kandidat til Watts On, fordi værket officielt viser fjernvarme i Watts On ([fh.dk/watts](https://www.fh.dk/watts)). Kunder hos Hornbæk Fjernvarme er undtaget. **Novafos** er ikke tilføjet (kun vand).
- Værk-vælgeren viser `✅` / `🧪` for Watts On-værker på samme måde som for KMD-værker.

## [0.3.2] - 2026-11-22

### Rettet
- Efter MitID-godkendelse kunne login hos visse KMD-værker ende med `OIDC authorization code not returned` og URL'en `/Identity/Account/ExternalLogin?…client_id=48…`. `48…` er Kredsløbs OIDC-klient. For andre værker (fx **Energi Ikast**, som bruger **Min Forsyning 2**) faldt opdagelsen tavst tilbage til Kredsløbs klient, så MitID lykkedes, men værkets portal ikke kendte brugeren. Fra v0.3.2 opdages Min Forsyning 2 (`login_type=mf`, fælles klient, `utility` fra plant-nummer) automatisk, og en mislykket opdagelse er en tydelig fejl i stedet for et stille Kredsløb-fald tilbage.
- Auto-POST af SAML/callback-formularer følger nu også formularer uden `action` (de postes til den aktuelle URL) og tager named submit-knapper med. Interaktive sider (første login, opret bruger, vilkår) postes ikke automatisk; kortet viser en dansk besked om at logge ind én gang i en almindelig browser først. Side-titel og eventuelle `error`/`remoteError` logges renset (uden e-mail, tokens eller CPR).

### Watts On / Aalborg Forsyning
- Varme-endpointet er verificeret live i Aalborg af [@dkvand](https://github.com/dkvand) (PR #9, live-test og sparring): `heating/api/v1/devices/{device_id}/consumption/recent` med `?newerThan=`. Feltnavne `En` (kWh), `Vol` (m³) og `TI`/`TO` (frem-/returtemperatur) genkendes. De gamle gættede stier beholdes som fallback.

## [0.3.1] - 2026-11-22

### Rettet
- Efter opdatering fra v0.2.x til v0.3.0 kunne MitID-QR-koden mangle på dashboard-kortet. Home Assistant cacher filer under `/local/` i 31 dage, så browseren eller Companion-appen kunne blive ved med at køre det gamle kort, som læste de fjernede attributter `mitid_qr_svg` / `mitid_otp_code`. Integrationen opretter eller opdaterer nu selv Lovelace-ressourcen til `/local/js/kmd-easy-energy-card.js?v=<version>`. I YAML-tilstand logges en advarsel, hvis URL'en mangler eller er uversioneret.

## [0.3.0] - 2026-11-22

Første stabile **0.3.0**-udgivelse. Samler indholdet fra `v0.3.0-beta.1`–`v0.3.0-beta.4` plus en tydeligere førstegangsguide. Bygger videre på **v0.2.1** (CET-timehentning, spidstime-grafer, fjernet Aula-script).

### Førstegangsopsætning
- README og config-flowet gør det tydeligt, at **Submit kun opretter integrationen**. MitID-login sker bagefter på dashboard-kortet med **🚀 Gem & Start MitID-synkronisering**.
- Ser man en opsætningsdialog med "Login & Token" og et Access token-felt, kører man den gamle **v0.2.0** og skal opdatere i HACS.

### Session-baseret synkronisering (KMD)
- **Hvert tryk på Synkroniser er ét MitID-login.** Data siden sidste synkronisering hentes (inkl. Energy-timestatistik), og KMD-adgangen (gyldig ca. 1 time, ingen refresh token) kasseres straks og gemmes aldrig.
- **Ingen baggrundspolling** mod KMD. Efter genstart vises de senest hentede tal fra den private cache uden kontakt til KMD.
- **Ingen reauth/reparation for udløbet token.** Kun et login, der reelt fejler, vises som fejl på kortet.
- **Blød weekend-påmindelse:** Lørdag og søndag vises en rolig info-linje under Synkroniser-knappen, hvis der ikke er synkroniseret torsdag, fredag eller lørdag samme uge. Ingen notification, repair eller push. `binary_sensor.<værk>_sync_reminder` kan bruges i egne automatiseringer og kan slås fra.
- Ny sensor `sensor.<værk>_last_synced` (*Sidst synkroniseret*). Første synkronisering henter op til 12 måneders timehistorik; senere synkroniseringer udfylder hullet. Statistikken skrives pr. time (upsert).
- **Migrering (config entry 1.1 → 1.2):** et ev. gemt token fjernes automatisk.

### MitID: QR fra tablet/computer og stabil scanning
- Skift til 4-cifret engangskode er **kun** nødvendigt, når opsætningen sker på **samme telefon** som MitID-appen. På tablet eller computer scannes QR-koden på kortet.
- Kortet viser begge MitID QR-frames (skifter hvert sekund), større QR med hvid baggrund og ISO quiet zone.
- In-place QR-opdatering uden at rive Shadow DOM ned; ingen kunstig 1,2 s forsinkelse efter MitID long-poll.
- OTP/QR leveres via websocket-abonnementet `kmd_easy_energy/mitid/subscribe` (virker også for ikke-admin, typisk vægtablet). Eventet `kmd_easy_energy_mitid_challenge` indeholder kun status. Koden lægges ikke på sensorattributter eller i recorderen.

### Udetemperatur
- Rækkefølge: valgfri HA-udetemperatursensor (døgnmiddel fra recorderens langtidsstatistik) → Open-Meteo ved HA-hjemmelokation → værkets placering.
- **Rettet:** tidligere blev værkets koordinater kopieret ind ved opsætning, så HA-hjemmelokationen reelt aldrig blev brugt.
- Kilden vises på kortet og i attributterne `temp_source` / `outdoor_temp` (ingen koordinater). **Migrering 1.2 → 1.3** (ikke brudende).

### E|Forsyning (eksperimentel, ikke testet live)
- Ny backend for værker på **E|Forsyning** (eforsyning.dk / DFF-EDB). Første værk: **Hjørring Varmeforsyning**. Login med forbrugernummer + webpinkode (intet MitID). Automatisk daglig synkronisering. Daglige aflæsninger (ingen timedata, saldo eller budgetprognose).
- Protokollen er studeret fra og genimplementeret efter [kpoppel/homeassistant-eforsyning](https://github.com/kpoppel/homeassistant-eforsyning) (Apache-2.0).

### Watts On / Aalborg Forsyning (eksperimentel, uofficiel, ikke testet live)
- Ny backend `wattson` for fjernvarme vist i **Watts On**-appen. Login i browseren uden MitID (indsæt den sidste `msauth://`-adresse). Kun et refresh token gemmes. Varme-endpoint og feltnavne er gættet; ukendt data skjules frem for at gættes.
- Bygget med [TheRealBatBro/Home-Assistant-Novafos-V2](https://github.com/TheRealBatBro/Home-Assistant-Novafos-V2) (MIT) som inspiration.

### Kapabilitetsstyret kort og entiteter
- Coordinatoren udstiller `capabilities`. Kortet skjuler grafer, KPI-felter og indsigter uden data og viser kun MitID-UI, når backenden bruger MitID. Sensorer oprettes kun, når backenden kan udfylde dem.

### Sikkerhed, Energy-dashboard og pakning
- Forbrugscache skrives til Home Assistants private `.storage` (`kmd_easy_energy.<entry_id>`), ikke til den uautentificerede `www/`-mappe. Eksisterende `www/`-cache migreres og slettes.
- Diagnostics-platform redigerer tokens, MitID-brugernavn, kunde-/måler-id, GPS-koordinater, push-service og adresser.
- Timeværdier (kWh og m³) importeres som eksterne statistikker (`kmd_easy_energy:energy_<entry>` / `:volume_<entry>`) til Energy-dashboardet. Valgfri varmepris i kr./kWh (Kredsløb: offentlig takst for indeværende år). Sensorer for motivationstarif, kWh pr. graddag, årsprognose og unormalt forbrug. Integrationen sender **ingen** lækage-notifikationer af sig selv.
- Entitetsnavne bruger `translation_key` (dansk og engelsk). Vendoret MitID BrowserClient har LICENSE (MIT, © 2024 Hundter) og et root-`NOTICE`. Minimum Home Assistant i `hacs.json` er **2024.12.0**. Forberedte brand-ikoner ligger i `docs/home-assistant-brands/`.

### Brudende ændringer (for tilpassede dashboards og automatiseringer)
- Attributterne `mitid_otp_code` og `mitid_qr_svg` er fjernet. Brug det medfølgende kort 0.3.0 eller websocket-abonnementet `kmd_easy_energy/mitid/subscribe`.
- Access tokens gemmes ikke, og der er ingen baggrundspolling. Automatiseringer, der kaldte `kmd_easy_energy.refresh` for at hente nye data, skal i stedet bruge `start_mitid_sync` (kræver godkendelse i MitID-appen).
- Attributten `token_expired` og reauth-flowet er fjernet.

## [0.2.1] - 2026-11-22

### Ændret
- Timehenting i `kmd_client.py` bruger nu Europe/Copenhagen midnat (UTC-bounds) og falder tilbage til dag-for-dag, hvis enkelte timer mangler i flerdages-svar.
- Timeprofilen (MTD) gennemsnitliggør pr. time pr. dag og ignorerer punkter uden for de komplette dage.
- Dashboard-kortet (`0.2.1`): bedre graf-læsbarhed og automatisk spidstime-detektion.
- Fjernet død Aula-login-kode (`mitid_browserclient/login_flows/aula.py`).

## [0.2.0] - 2026-11-22


### Tilføjet
- **100% lokal MitID-godkendelse i Home Assistant (ren Python):** OIDC PKCE + NemLog-in + MitID SRP (`BrowserClient` + `UrllibSession`) uden behov for Chromium eller ekstern add-on.
- **Smart værk-vælger:** 17 danske fjernvarmeværker opdelt i `✅ Bekræftet` (Kredsløb) og `🧪 Afventer første test` / `🔎 Kandidater`, plus brugerdefineret portal-URL.
- **Plug-and-Play Lovelace-kort (`custom:kmd-easy-energy-card`):**
  - Førstegangsopsætnings-wizard med live visning af 4-cifret MitID-engangskode eller QR-kode.
  - 4 KPI-kort, 5 interaktive SVG-grafer og 4 Open-Meteo vejrkorrelerede indsigter.
  - Indbygget anonymiseret feedback-knap til at bekræfte eller fejlmelde nye værker på GitHub.
  - Automatisk installation af `/local/js/kmd-easy-energy-card.js` ved opsætning af integrationen.
- **Rettet `ZoomLevel=3` timeprofil:** Automatisk dag-for-dag fallback med deduplikering, når KMD's API returnerer nul-udfyldte flerdages-svar.

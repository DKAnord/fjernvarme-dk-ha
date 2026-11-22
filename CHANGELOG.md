# Changelog

Alle væsentlige ændringer i **Fjernvarme (KMD Easy Energy) – HA Connector & Dashboard** dokumenteres her.

## [0.3.0-beta.3] (efter 0.3.0-beta.2)

### Tilføjet: E|Forsyning-backend (eksperimentel, ikke testet live — beta-testere søges)
- Ny backend for værker på **E|Forsyning** (eforsyning.dk / DFF-EDB). Første værk: **Hjørring Varmeforsyning** (forsyningid `B30A6948-2461-4827-B8EB-5D93169CCB8B`, fundet på den offentlige side eforsyning.dk/hjvarme). *Andet E|Forsyning-værk* kan sættes op med værkets forsyningid.
- `utilities.json` har nyt felt `backend` (`kmd` for alle eksisterende værker, `eforsyning` for nye).
- Opsætning med **forbrugernummer + webpinkode** i stedet for MitID (gemmes i config entry, logges aldrig, redigeres i diagnostics). Valg af installation, hvis kontoen har flere. Reconfigure kan skifte login.
- **Automatisk daglig synkronisering** for E|Forsyning (standard ca. kl. 06:17, kan ændres/slås fra). Weekend-påmindelsen er slået fra som standard for E|Forsyning. Ny tjeneste `kmd_easy_energy.sync` (uanset backend); knappen hedder *Synkroniser nu* for E|Forsyning.
- Daglige aflæsninger mappes til samme data som KMD-backenden (dagligt, månedligt, år kun ved fuld dækning, m³, m³-vægtet returtemperatur). Energy-statistik importeres med én række pr. døgn. Der er ingen timedata, saldo eller budgetprognose fra E|Forsyning.
- Protokollen er studeret fra og genimplementeret efter [kpoppel/homeassistant-eforsyning](https://github.com/kpoppel/homeassistant-eforsyning) (Apache-2.0). Afledt fil markeret, licenstekst medfølger, kreditering i README og NOTICE.

### Tilføjet: Kapabilitetsstyret kort og entiteter (alle backends)
- Coordinatoren udstiller `capabilities` (fx `hourly`, `daily`, `monthly`, `temperatures`, `volume`, `cost`, `billing`, `forecast`, `mitid`, `reminder`, `auto_sync`) = det backenden kan levere **og** der faktisk er data til, samt `backend_capabilities`.
- Kortet skjuler grafer, KPI-felter og indsigter uden data (ingen tomme grafer eller "–"-felter) og viser kun MitID-UI, når backenden bruger MitID. Ældre integrationer uden attributten viser alt som før.
- Sensorer og binære sensorer oprettes kun, når backenden kan udfylde dem (fx ingen saldo-sensor for E|Forsyning). Uændret for KMD-værker.

## [0.3.0-beta.2] (efter 0.3.0-beta.1)

### Brudende ændringer
- Access tokens gemmes ikke, og der er ingen baggrundspolling: nye data kommer kun ved **Synkroniser** (MitID). Automatiseringer, der kaldte `kmd_easy_energy.refresh` for at hente nye data, skal i stedet bruge `start_mitid_sync` (kræver godkendelse i MitID-appen).
- Attributten `token_expired` og reauth-flowet er fjernet. Live-kode/QR leveres via websocket, ikke bus-event (se nedenfor).

### MitID: QR fra tablet/computer og tydeligere vejledning
- Kort, README og tekster siger nu tydeligt, at skiftet til 4-cifret engangskode **kun** er nødvendigt, når opsætningen sker på **samme telefon** som MitID-appen. Opsætter man på en tablet eller computer, scanner man bare QR-koden på kortet med MitID-appen.
- MitID's animerede QR består af to billeder (p=1/p=2), som appen skal se begge. Backend sender nu begge billeder, og kortet skifter mellem dem hvert sekund i browseren. Før skiftede billedet kun, når MitID's long-poll svarede, så appen kunne have svært ved at læse koden.
- QR-koden vises større (op til 240 px med hvid kant) og med skarpe kanter (`crispEdges`), så den er lettere at scanne fra en skærm.
- Live-kode/QR leveres nu via integrationens eget websocket-abonnement `kmd_easy_energy/mitid/subscribe` i stedet for et bus-event:
  - Recorderen gemmer alle bus-events, så engangskode og QR endte tidligere i databasen. Eventet `kmd_easy_energy_mitid_challenge` indeholder nu kun status (`sync_state`, `sync_message`, `has_otp`, `has_qr`).
  - Virker også for ikke-admin-brugere (typisk vægtablet). `subscribe_events` på et custom event kræver admin.
  - En tablet, der åbner kortet midt i et login, får den aktuelle QR/kode med det samme.
- HA-notifikationen oprettes via helperen i stedet for tjenestekaldet `persistent_notification.create` (der ville lægge koden i et `call_service`-event i recorderen). QR-notifikationen oprettes kun én gang pr. login, og QR/kode sendes kun til kortet, når den faktisk ændrer sig.
- Notifikationen fjernes også ved fejl. Status `verified` (kode/QR godkendt) sendes én gang.
- Den vendorede `BrowserClient` logger ikke længere selve engangskoden.

### Session-baseret synkronisering (ingen baggrundspolling, intet gemt token)
- **Hvert tryk på Synkroniser = ét MitID-login.** Data siden sidste synkronisering hentes (inkl. Energy-timestatistik), og KMD-adgangen kasseres straks. Access tokens gemmes ikke længere i config entry eller cache.
- **Ingen automatisk polling mod KMD** (`update_interval` er `None`). Coordinatoren genindlæser kun den private cache. Efter genstart vises de senest hentede tal uden kontakt til KMD.
- **Ingen reauth/reparation for udløbet token.** `ConfigEntryAuthFailed`, reauth-trinnene (`reauth_confirm`, `reauth_mitid`), advarslen om tokenalder og attributten `token_expired` er fjernet. Kun et login, der reelt fejler (fx HTTP 401/403 lige efter MitID), vises som fejl på kortet/sync-status.
- Felterne til at indsætte token er fjernet fra config- og reconfigure-flowet. Tjenesten `update_token` er bevaret som avanceret engangs-synkronisering med et selvhentet token (gemmes ikke). `refresh` genindlæser nu kun cache.
- **Ny sensor** `sensor.<værk>_last_synced` (*Sidst synkroniseret*, tidsstempel) og attributterne `last_sync`, `days_since_sync`, `sync_reminder`, `sync_reminder_message`, `sync_reminder_short` på overbliks-sensoren.
- **Blød weekend-påmindelse:** Lørdag og søndag (Europe/Copenhagen) vises en lille, rolig info-linje (💧, neutral/blød blå, ingen rød fejl-styling) lige under Synkroniser-knappen: *"Det er X dage siden sidste synkronisering — tryk Synkroniser, når du har et øjeblik."*, hvis der ikke er synkroniseret torsdag, fredag eller lørdag samme uge (en synkronisering søndag fjerner den). Mandag–fredag aldrig. Ingen persistent notification, repair eller push. Ny `binary_sensor.<værk>_sync_reminder` til egne automatiseringer. Kan slås fra under indstillinger (standard: til).
- **Historik:** Første synkronisering henter op til 12 måneders timehistorik. Senere synkroniseringer udfylder hullet fra sidste gemte time frem til indeværende måned og op til tre manglende måneder. Statistikken skrives pr. time (upsert), så flere synkroniseringer samme dag ikke giver dubletter.
- **Migrering (config entry 1.1 → 1.2):** Et gemt token fjernes automatisk fra data og options. Indgangen virker videre med de cachede data. *Sidst synkroniseret* sættes ud fra cachens `updated`, indtil næste synkronisering.
- Kortet: Synkroniser-knappen starter altid MitID-synkronisering. Banneret viser *Sidst synkroniseret*; weekend-påmindelsen vises som en rolig info-linje under knappen. "Token udløbet" er fjernet. Manuelt token hedder nu "Synkroniser én gang med token".

## [0.3.0] - 2026-11-22

### Sikkerhed og privatliv
- Forbrugscache skrives nu til Home Assistants private `.storage` (`kmd_easy_energy.<entry_id>`), ikke til den uautentificerede `www/`-mappe (`/local/varme/...`).
- Eksisterende `www/varme/kmd_easy_energy_cache*.json` migreres automatisk og slettes bagefter. Filen `www/varme/data.json` bruges ikke længere som seed.
- MitID-engangskode og QR-kode lægges ikke længere på sensorattributter (og dermed ikke i recorder). De vises via et midlertidigt `kmd_easy_energy_mitid_challenge`-event (fra næste version: websocket-abonnement, se ovenfor), en persistent_notification og (valgfrit) push, hvor koden kun står i beskeden — aldrig i titlen.
- URL'er med `code=` / tokens redigeres i logs og logges på DEBUG.
- `async_remove_entry` rydder privat storage og eventuelle efterladte `www/`-cachefiler.

### Opførsel
- HTTP 401/403 rejser `ConfigEntryAuthFailed` og starter reauth-flowet (`reauth_confirm` / `reauth_mitid`), hvor man kan indsætte et token eller starte MitID. Har integrationen cache, bliver sensorerne stående med sidste kendte værdier.
- Hvis første opdatering fejler midlertidigt, men der findes cache, indlæses integrationen med cachen i stedet for at fejle opsætningen (`ConfigEntryNotReady` kun uden cache).
- Open-Meteo-arkivet hentes højst én gang i døgnet (Europe/Copenhagen).
- Config flow sætter `unique_id` pr. værk, så det samme værk ikke kan tilføjes to gange. Eksisterende entries migreres ved opstart.
- Ny tjeneste `kmd_easy_energy.start_mitid_sync` (bruges af dashboard-kortet i stedet for at gætte `button.*_sync`).
- Volumen-sensoren bruger `device_class: water` (cirkulerende fjernvarmevand i m³, ikke drikkevand), så den kan tilføjes på Energy-dashboardets volumen-spor.
- `requests` er tilføjet som eksplicit krav i manifestet. Den døde `UPDATE_INTERVAL`-konstant bruges nu som 30-minutters coordinator-interval.

### Energy-dashboard, tarif og danske indsigtssensorer
- Timeværdier (kWh og m³) importeres som eksterne statistikker (`kmd_easy_energy:energy_<entry>` / `:volume_<entry>`) via `async_add_external_statistics`, så Energy-dashboardet kan tilbagefylde rigtige timer i stedet for at bruge måned-til-dato-sensorerne. Historikken udvides gradvist med op til to tidligere måneder pr. døgn.
- Valgfri varmepris i kr./kWh (og ev. kr./m³) i indstillingerne. For Kredsløb er standarden den offentliggjorte takst for indeværende kalenderår (2026: 0,6680 kr./kWh, 2027: 0,7175 kr./kWh, motivation 0,010 / 0,01075 kr./kWh/°C) fra [Kredsløbs prisside](https://www.kredslob.dk/privat/fjernvarme/fjernvarmepriser). Øvrige værker har ingen opfundet standard — brugeren indtaster selv. Der gættes ikke på en m³-pris.
- Sensorer for motivationstarif (bonus/neutral/gebyr og kr./kWh-regulering), kWh pr. graddag, normalår-korrigeret årsforbrug og årsprognose. `binary_sensor` for gebyr-returtemperatur og unormalt forbrug (samme ugedag, HDD-justeret). Integrationen opretter **ingen** notifikationer eller automatiseringer for lækage-flaget.
- Open-Meteo 7-dages HDD hentes højst én gang i døgnet (Europe/Copenhagen), ligesom arkivet.

### Integration og pakning
- Entitetsnavne bruger `translation_key` med dansk og engelsk (volumen hedder tydeligt fjernvarmevand).
- Ny diagnostics-platform, der redigerer tokens, MitID-brugernavn, kunde-/måler-id og adresser. Store serier er kun talt, ikke dumpet.
- Vendoret MitID BrowserClient har LICENSE (MIT, © 2024 Hundter) og et root-`NOTICE`. Død `Helpers.py` er fjernet (Aula-flowet var allerede væk i 0.2.1).
- Manifest: `integration_type: service` og `loggers`. `hacs.json`: `render_readme` og minimum HA **2024.12.0** (reauth-helpers). hassfest-action er pinned i stedet for `@master`.
- Forberedte brand-ikoner og instruktion til en PR mod [home-assistant/brands](https://github.com/home-assistant/brands) ligger i `docs/home-assistant-brands/` — selve PR'en er et maintainer-valg.

Versionen forbliver **0.3.0** (ikke 0.4.0): 0.3.0 er endnu ikke udgivet, så al den nye funktionalitet samles i ét uudgivet hop oven på 0.2.1.

Bygger videre på **v0.2.1** (CET-timehentning, spidstime-grafer, fjernet Aula-script).

### Bemærk (brudende for tilpassede dashboards)
- Attributterne `mitid_otp_code` og `mitid_qr_svg` er fjernet. Brug det medfølgende kort 0.3.0, eller lyt til eventet `kmd_easy_energy_mitid_challenge`.

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

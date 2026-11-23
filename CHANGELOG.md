# Changelog

Alle væsentlige ændringer i **Dansk Fjernvarme** (tidligere *Fjernvarme (KMD Easy Energy)*) dokumenteres her.

## [1.2.0] - 2026-11-23

### Tilføjet & Bekræftet
- **Middelfart Fjernvarme bekræftet live (E|Forsyning):** Markeret som ✅ **Bekræftet** efter live-verifikation fra **Jesper Madsen**, inkl. officiel takst pr. 1. juli 2026 (`0,705 kr./kWh` inkl. moms, `±1 %/°C` motivationstarif med maks. `±20 %` regulering samt `37 °C` standard forventet returtemperatur).
- **Automatisk forventet returtemperatur (`Forv_Retur`) fra E|Forsyning:** Når et E|Forsyning-værk leverer feltet `Forv_Retur` i dagsdataene, gemmes det m³-vægtet og bruges automatisk som forventet returtemperatur i bonus-/gebyrberegning og grafer, medmindre du selv har indtastet andre grænser.
- **Hurtig indtastning af varmepris (`kr./kWh`), forventet returtemperatur (`°C`) & motivation (`%/°C`) direkte på kortet:** Tryk på **⚙️** på dashboard-kortet (virker nu for både KMD, E|Forsyning og Watts On) eller følg det diskrete hint, når kWh-pris ikke er sat endnu. Integrationens indstillingsdialog hedder nu også *Dansk Fjernvarme — Indstillinger* og har fået et dedikeret `% pr. °C`-felt samt `0 = automatisk` for returtemperaturgrænser.

### Forbedret
- **Skarpere fejlrapporter & danske MitID-fejltekster:** GitHub-fejlrapporter skelner nu mellem `Card Version` og backendens `Integration Version`, vedlægger sanitiseret `Sync State` / `Last Sync Message` uden persondata, og oversætter ukendt MitID Bruger-ID samt parallelle MitID-sessioner til tydelige danske fejlbeskeder.

## [1.1.0] - 2026-11-23

### Tilføjet & Bekræftet
- **Frederikshavn Forsyning bekræftet live (KMD / MitID):** Markeret som ✅ **Bekræftet** efter live-verifikation fra `@tirolel` ([issue #24](https://github.com/DKAnord/fjernvarme-dk-ha/issues/24), `MWh` & `M3`).
- **Sorø Fjernvarme tilføjet og bekræftet live (E|Forsyning):** Første fuldt bekræftede E|Forsyning-værk takket være `@Crallebab` ([issue #25](https://github.com/DKAnord/fjernvarme-dk-ha/issues/25)), inkl. forudfyldt `forsyningid` (`CE44A147-CE18-483B-81AF-29A188E33067`) og officiel 2026-takst (`0,981 kr./kWh` inkl. moms samt `±1 %/°C` under 35 °C / over 45 °C).
- **20 nye forudfyldte E|Forsyning-fjernvarmeværker (22 i alt):** Horsens, Vestforbrænding, Egedal, Fredericia, Vejle, Sønderborg Varme, SONFOR Varme, Køge, Høje Taastrup, Avedøre, Middelfart, Solrød, Thisted, Assens, Ringkøbing, Hvide Sande, Kibæk, Kjellerup, Ansager og Dianalund — alle verificeret offentligt mod `GetVaerkSettings`.
- **Live søgbar E|Forsyning-værksliste (300+ værker):** Ny mulighed i opsætningen (*🔎 Søg blandt alle E|Forsyning-værker*) henter alle varmeværker direkte fra `eforsyning.dk` (vandværker filtreres fra), slår `forsyningid` op automatisk og falder pænt tilbage til manuel indtastning ved netværksfejl.
- **Automatisk opslag fra portal-URL eller slug (intet F12 påkrævet):** Under *Andet E|Forsyning-værk* (og genkonfigurering) kan du nu indsætte en portal-URL (f.eks. `https://eforsyning.dk/horsens/`), et slug (`horsens`) eller en `forsyningid`-UUID. Integrationen henter automatisk `forsyningid`, værknavn og portal-URL — og vælger automatisk rigtig enhed ved multi-værkssider eller viser en vælger.
- **E|Forsyning-vælger & statusbadge:** Værk-vælgeren og opsætningsguiden for E|Forsyning skelner nu mellem ✅ **Bekræftet live** (Sorø Fjernvarme) og 🧪 **Afventer 1. test** (øvrige værker).

## [1.0.1] - 2026-11-22

### Rettet
- **Indsigter efter skift fra El til Varme:** Månedssøjlerne blev opdateret, men R², grundlast, kWh/HDD og døgnrytme kunne blive liggende på den gamle elmålers tal. Vejrarkivet (og dermed indsigterne) blev kun beregnet én gang om dagen, og time-/dagshistorik for den forrige måler blev ikke nulstillet. Fra v1.0.1 genberegnes indsigterne ved hver synkronisering ud fra de aktuelle månedstal, og et skift af kundeforhold/måler rydder den cached forbrugshistorik (ikke udetemperaturen) og henter varmemålerens data forfra. Home Assistant Energy-statistik skrives derefter på ny (upsert) for den valgte måler.

## [1.0.0] - 2026-11-22

Første stabile **1.0.0**-udgivelse (ude af beta) af **Dansk Fjernvarme** (`DKAnord/fjernvarme-dk-ha`, ikke-breaking teknisk domæne `kmd_easy_energy`).

### Samlet højdepunkt i 1.0.0
- **Tre danske fjernvarmebackends i én lokal integration:** **KMD Easy Energy / Min Forsyning 2** (100 % lokalt MitID-login med QR eller 4-cifret engangskode), **Watts On** (browser-login med roterende refresh token) og **E|Forsyning** (forbrugernummer + webpinkode).
- **Bekræftet live på tre værker:** **Kredsløb**, **Energi Ikast** (Min Forsyning 2, `@BenzDK` i #19) og **Aalborg Forsyning** (Watts On, `@dkvand` i PR #9).
- **Rigtig varmemåler på Min Forsyning 2 (inkl. fra 0.3.7):** Konti med flere kundeforhold vælger automatisk **Varme** (aldrig El eller Vand), og konti med flere varmemålere kan vælge den rigtige under integrationens indstillinger.
- **Omkostningsestimater i kr. på tværs af alle udbydere:** 4 nye estimatsensorer + indbygget `💰 Estimeret forbrug i kr.`-panel på dashboard-kortet, procentbaseret motivationstarif og skærpede R²/HDD-indsigter.
- **HACS Marketplace-klar:** Fuld HACS + Hassfest-validering, ikke-blokerende opstart og XSS-hærdning i kortet.

## [0.3.7] - 2026-11-22

### Rettet
- **KMD / Min Forsyning 2 med flere kundeforhold:** En konto kan have el som første (standard) kundeforhold og fjernvarme+vand som et senere. Integrationen tog tidligere `Customers[0]` og `meters[0]`, så kortet kunne vise elmålerens flade kWh-serie (E17, GSRN/EAN 5713…) i stedet for **Varme**. Fra v0.3.7 gennemgås alle kundeforhold, og der vælges automatisk varmemåleren (ikke El, ikke Vand). Hvis der er flere varmemålere, vælges den under integrationens indstillinger efter første synkronisering — el vælges aldrig tavst.
- **Indsigter:** Måneder uden data eller med 0 kWh springes over. kWh/HDD vises kun for år med nok data og reelt rumvarmeforbrug (ikke 0,00). Kortet påstår ikke længere, at forbruget "følger temperaturen tæt", når R² er lav, og skjuler HDD-året, når det ikke kan beregnes.

## [0.3.6] - 2026-11-22

### HACS-kvalitet & sikkerhed
- **Ikke-blokerende versionsopslag:** `async_ensure_lovelace_card_resource` læser nu `manifest.json` via `hass.async_add_executor_job`, så Home Assistants event loop ikke blokeres ved opstart.
- **Sikkerhedshærdning i dashboard-kortet:** URL-scheme-tjek (`https?://`) før `window.open` på portal-knappen samt `esc()` på de sidste SVG `data-tip`-attributter.

## [0.3.5] - 2026-11-22

### Navneskifte & HACS Marketplace-forberedelse (ikke breaking)
- **Nyt navn og repo:** Integrationen hedder nu **Dansk Fjernvarme** i HACS og Home Assistant, og GitHub-repoet er flyttet til [`DKAnord/fjernvarme-dk-ha`](https://github.com/DKAnord/fjernvarme-dk-ha) (GitHub omdirigerer automatisk fra det gamle navn).
- **100 % ikke-breaking:** Teknisk `domain` (`kmd_easy_energy`), kort-type (`custom:kmd-easy-energy-card`) og alle entitet-/statistik-ID'er er bevaret uændret, så eksisterende opsætninger og Energy-historik fortsætter uden afbrydelse.
- **Tak & Credits:** Tilføjet en samlet credits-sektion i `README.md` til [kpoppel/homeassistant-eforsyning](https://github.com/kpoppel/homeassistant-eforsyning) (Apache-2.0), [TheRealBatBro/Home-Assistant-Novafos-V2](https://github.com/TheRealBatBro/Home-Assistant-Novafos-V2) (MIT), [Hundter/MitID-BrowserClient](https://github.com/Hundter/MitID-BrowserClient) (MIT) og [@dkvand](https://github.com/dkvand).

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

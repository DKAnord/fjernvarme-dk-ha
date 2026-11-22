# Changelog

Alle væsentlige ændringer i **Fjernvarme (KMD Easy Energy) – HA Connector & Dashboard** dokumenteres her.

## [0.3.0] - 2026-11-22

### Sikkerhed og privatliv
- Forbrugscache skrives nu til Home Assistants private `.storage` (`kmd_easy_energy.<entry_id>`), ikke til den uautentificerede `www/`-mappe (`/local/varme/...`).
- Eksisterende `www/varme/kmd_easy_energy_cache*.json` migreres automatisk og slettes bagefter. Filen `www/varme/data.json` bruges ikke længere som seed.
- MitID-engangskode og QR-kode lægges ikke længere på sensorattributter (og dermed ikke i recorder). De vises via et midlertidigt `kmd_easy_energy_mitid_challenge`-event, en persistent_notification og (valgfrit) push, hvor koden kun står i beskeden — aldrig i titlen.
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

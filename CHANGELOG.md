# Changelog

Alle væsentlige ændringer i **Fjernvarme (KMD Easy Energy) – HA Connector & Dashboard** dokumenteres her.

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

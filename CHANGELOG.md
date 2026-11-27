# Changelog

Alle væsentlige ændringer i **Dansk Fjernvarme** (tidligere *Fjernvarme (KMD Easy Energy)*) dokumenteres her.

## [1.3.6] - 2026-11-27

### Bekræftet & Forbedret
- **Sønderborg Varme bekræftet live ([issue #45](https://github.com/DKAnord/fjernvarme-dk-ha/issues/45), tak til `@CarstenLeonhardt`):** Markeret som ✅ **Bekræftet** E|Forsyning-værk (`sonderborg-varme`, `https://www.sonderborg-varme.dk/eforsyning/`, verificeret med `kWh`, `m³` og `°C` — nu **18** live-bekræftede værker), inkl. eksisterende officielle 2026/2027-takster (`0,58` / `0,6615 kr./kWh` inkl. moms, fast bidrag `27,50 kr./m²/år`, valgfrit målerabonnement `687,50 kr./år` og asymmetrisk motivationstarif `-1,0 %/°C` bonus / `+0,5 %/°C` tillæg).
- **Kortressource:** Opdateret cache-busting ressource-URL til `/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.6`.

## [1.3.5] - 2026-11-27

### Rettet & Forbedret
- **Grenaa Varmeværk A.m.b.A. tilføjet og bekræftet live + 2026-takst ([issue #48](https://github.com/DKAnord/fjernvarme-dk-ha/issues/48), tak til `@cctreeacdk`):** Tilføjet som dedikeret ✅ **Bekræftet** E|Forsyning-værk (`grenaa-varmevaerk`, `forsyningId: BE112409-C45D-4E63-BFF6-1C4E8F9ED990`, `https://eforsyning.dk/grenaa-varmevaerk/`) med automatisk opgradering fra `eforsyning-custom` samt officiel 2026-takst fra [Takstblad 2026](https://grenaa-varmevaerk.dk/p/Grenaa%20Varmev%C3%A6rk/%C3%98konomi/Takstblad-2026.pdf) (`0,39 kr./kWh` inkl. moms, `28,25 kr./m²/år` effektbidrag, `975,00 kr./år` målerabonnement for 1,5 m³-måler og `±1 %/°C` motivationstarif med `32–35 °C` neutralzone; bruger automatisk `Forv_Retur` fra E|Forsyning hvis oplyst).
- **Vestforsyning (Holstebro) bekræftet live (KMD / Min Forsyning):** Markeret som ✅ **Bekræftet** efter live-verifikation med MitID (nu **17** live-bekræftede værker), inkl. eksisterende officielle 2026/2027-takster (`0,67375` / `0,70125 kr./kWh` inkl. moms, fast bidrag `20,40` / `21,2125 kr./m²/år` samt `±0,00375 kr./kWh/K`).
- **Hurtigere første synkronisering på Watts On & E|Forsyning (`coordinator.py`):** Ved helt ny opsætning uden tidligere synkronisering (`last_sync is None`) starter første automatiske synkronisering nu efter **10 sekunder** i stedet for 120 sekunder, så sensorerne udfyldes næsten med det samme (beholder 120 sek. forsinkelse ved almindelig Home Assistant-genstart med ældre cache).
- **Robust Watts On-målervalg & -opdagelse (`coordinator.py`, `api/wattson_client.py`):**
  - `async_sync_wattson()` respekterer nu et manuelt valgt `wattson_device_id` på tværs af alle fundne enheder før fallback til første varmemåler, så ikke-autoklassificerede målere fra opsætningsguiden ikke længere afvises ved første synkronisering.
  - `WattsOnClient.async_devices()` fletter manglende `kind`, `type` og `unit`, når samme `deviceId` optræder flere steder i `provisioning/api/v1/locations/{loc_id}`.
- **`sync_message` i diagnostics (`diagnostics.py`):** **Download diagnostik** inkluderer nu den sanitiserede `sync_message` (ingen tokens eller persondata), så fejl ved første synkronisering fremgår direkte af supportfiler.
- **Fjernet Høje Taastrup Fjernvarme fra E|Forsyning (`utilities.json`, `api/eforsyning_client.py`, `README.md`):** Høje Taastrup Fjernvarme er overgået til egen selvbetjeningsportal på `selvbetjening.htf.dk`, så værket er fjernet fra de forudfyldte presets og ekskluderet (`htf`) fra E|Forsyning-søgningen (nu **63/63** forudfyldte værker med officielle 2026/2027-takster).
- **Kortressource:** Opdateret cache-busting ressource-URL til `/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.5`.

## [1.3.4] - 2026-11-27

### Tilføjet & Rettet
- **Ekstern Energy-dashboard prisstatistik (`kmd_easy_energy:cost_<entry_id>`) ([issue #43](https://github.com/DKAnord/fjernvarme-dk-ha/issues/43), tak til `@JBoye`):**
  - Importerer nu en separat ekstern omkostningsstatistik (`DKK`, `unit_class=None`) på præcis de samme time- eller døgnbuckets som `kmd_easy_energy:energy_<entry_id>`, klar til Home Assistant Energy-dashboardets valg *Brug en entitet, der sporer de samlede omkostninger* (*Use an entity tracking the total costs*).
  - Beregner variabel varmeudgift ekskl. faste bidrag pr. time/døgn med automatiske takstskift (inkl. 2026→2027, `effective_from`-datoer og fallback til værkets tidligste takst ved 2025-historik) samt måneds-/dagsbaseret motivationstarif (inkl. dynamisk fremløbskurve, asymmetriske satser og maks.-grænse), når returtemperatur kendes.
  - **Recorder `sum`-forankring:** Slår eksisterende kumulativ sum før første bucket op i Home Assistants recorder (`statistic_during_period`), så rullende historik-afskæring på E|Forsyning/Watts On eller prisændringer i indstillingerne ikke giver store negative eller positive engangs-hop.
  - **Automatisk opstart- & indstillingsopdatering (`coordinator.py`):** Eksisterende opsætninger efterudfylder `cost_<entry_id>` én gang fra den lokale cache ved opstart uden et MitID-login, og pris-/motivationsændringer i indstillingerne genberegner automatisk `cost`-statistikken.
- **`last_reset` på `sensor.<værk>_year_cost` (`sensor.py`):** Eksponerer `1. januar` (`Europe/Copenhagen`) som `last_reset` på den årlige udgiftssensor (`SensorStateClass.TOTAL`), så årsskifte-nulstilling ikke registreres som et negativt beløb i statistikker.
- **Kortressource:** Opdateret cache-busting ressource-URL til `/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.4`.

## [1.3.3] - 2026-11-27

### Tilføjet & Forbedret
- **63/63 forudfyldte værker med officielle 2026/2027-takster (`utilities.json`):** Færdiggjort de sidste 4 eksisterende værker (`envafors` inkl. rettet portal-URL, `sonfor-varme`, `koge-fjernvarme`, `hoje-taastrup-fjernvarme`), tilføjet 22 nye live-verificerede værker (6 KMD Min Forsyning 2 + 16 E|Forsyning), tilføjet officielle 2027-takster på `beof`, `soroe-fjernvarme` (inkl. 2026-arealbidrag), `frederikshavn-forsyning` og `hadsund-fjernvarme` (nu 30 værker med 2027-takster), samt flyttet `nykobing-sj` (Nykøbing Sjælland Varmeværk) fra KMD til verificeret E|Forsyning (`17086977-7E29-4199-917D-1A76641671BC`, `https://eforsyning.dk/nsfv/`).
- **Ikrafttrædelsesdato (`effective_from`) i `tariff.py`:** `published_tariff()` / `resolve_tariff()` respekterer nu `effective_from`, så varslede midtårs-prisændringer (f.eks. Silkeborg `2027-02-01` og Nykøbing Sj. `2027-03-01`) først træder i kraft på selve datoen.
- **Asymmetriske motivationstariffer (`tariff.py`, `insights.py`, `coordinator.py`, `sensor.py`):** Understøtter separate bonus- og gebyrsatser (`motivation_bonus_*` / `motivation_penalty_*`), aktiveret for Høje Taastrup Fjernvarme (2026), Sønderborg Varme og Hvide Sande Fjernvarme.
- **Valgfrit standard målerabonnement (`kr./år`) med 1-kliks knap (`tariff.py`, `sensor.py`, `kmd-easy-energy-card.js`):** 47 værker har indbygget officielt målerabonnement udstillet som `suggested_fixed_fee_dkk_per_year` med placeholder og 1-kliks `↳ Brug standard (...)`-knap i ⚙️ (forbliver opt-in).
- **Kortressource:** Opdateret cache-busting ressource-URL til `/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.3`.

## [1.3.2] - 2026-11-27

### Tilføjet & Forbedret
- **Energi Ikast — officielle 2026/2027-takster (`utilities.json`):** Bundled officielle forbrugsafgifter fra Energi Ikasts takstblade for Ikast/Bording (`0,59625 kr./kWh` inkl. moms i 2026 og `0,57375 kr./kWh` i 2027), fast arealbidrag `25,00 kr./m²/år` (valgfrit ved indtastning af boligareal; `875,00 kr./år` målerabonnement kan indtastes som fast årsbidrag) samt den officielle fremløbsafhængige gebyr-only motivationstarif (`+3,75 kr./°C/MWh` inkl. moms over fremløbskurven `50→42 °C` til `70→32 °C`, maks. `+10 %`). Engesvang-kunder kan overstyre kWh-prisen i ⚙️ (`0,765` / `0,66375 kr./kWh` inkl. moms). Nu 37/41 værker med forudfyldte takster.
- **KMD `/api/cooling/getcoolinginfo` (returtemperatur, fremløbstemperatur & flow i m³):** Ved KMD / Min Forsyning 2-synkronisering hentes månedlige og daglige afkølingsdata best-effort fra `/api/cooling/getcoolinginfo` (`DegreesOut` til returtemperatur, `DegreesIn` til fremløbstemperatur og `Flow` som fallback for `m³` når måleren kun udstiller `kWh`-enheden i `customerActiveMeters`), samt aggregering fra `hourly_temp` når kun time-temperaturer findes.
- **Ingen blanke kort i dashboardet (`kmd-easy-energy-card.js`):** KPI-kort, grafer (måned, returtemperatur, timeprofil, MTD vs. YTD, daglig) og indsigtskort vises kun, når der faktisk findes reelle data — ikke blot ud fra statiske backend-kapabiliteter (skjuler også tomme `–` eller `0 kr.`-kort samt tomme temperaturakser/signaturer).
- **Lille note til manuel indtastning, som kan skjules (`dismiss`):** Når valgfrie felter (varmepris, manuel fremløbstemperatur til dynamisk kurve, eller boligareal til faste bidrag) kan låse flere tal op, vises en diskret note øverst med genvej til ⚙️ og en `✕`-knap, der huskes lokalt i browseren (`localStorage`, samt mulighed for at skjule helt i kortredigeringen).
- **KMD-indstillinger:** Tilføjet manuelt `Fremløbstemperatur (°C)`-felt for værker med dynamisk afkølingskurve, tydeligere `💾 Gem indstillinger`-knap og beskyttelse mod utilsigtet overskrivning af dynamiske returgrænser.
- **Kortressource:** Opdateret cache-busting ressource-URL til `/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.2`.

## [1.3.1] - 2026-11-26

### Tilføjet & Bekræftet
- **Kongerslev Fjernvarme tilføjet og bekræftet live + 2026/2027-takst ([issue #40](https://github.com/DKAnord/fjernvarme-dk-ha/issues/40), tak til `@cokeman0`):** Tilføjet som dedikeret ✅ **Bekræftet** E|Forsyning-værk (`kongerslev-fjernvarme`, `forsyningId: 4A530E73-227F-4ACB-9D9B-A84905470921`, `https://eforsyning.dk/kongerslev/`) med automatisk opgradering fra `eforsyning-custom` samt officiel 2026/2027-takst fra [Takstblad 2026–2027](https://kongerslevfjernvarme.dk/oekonomi/priser) (`0,6875 kr./kWh` inkl. moms pr. 1. sep. 2026–30. jun. 2027 og `±3 %/°C` incitamentstarif under `30 °C` / over `37 °C` ved `> 65 °C` fremløb; bruger automatisk `Forv_Retur` fra E|Forsyning hvis oplyst).

### Sikkerhed & Privatliv (opfølgning på HACS-review [`hacs/default#14752`](https://github.com/hacs/default/pull/14752))
- **Kryptografisk SRP-tilfældighed (`mitid_browserclient/CustomSRP.py`):** Skiftet fra `random.getrandbits(256)` til `secrets.randbits(256)` ved generering af SRP-hemmeligheden (`a`).
- **Fjernet MitID Bruger-ID fra fejllogs (`mitid_browserclient/BrowserClient.py`):** `user_id` skrives ikke længere til Home Assistant-fejlloggen ved mislykket identifikation eller authenticator-opslag, så bruger-ID'et ikke ender i delte logs eller fejlrapporter.
- **Kortressource:** Opdateret cache-busting ressource-URL til `/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.1`.

## [1.3.0] - 2026-11-26

### Ændret & Sikkerhed (HACS review `#14752`)
- **Integrationsejet statisk kortsti (`/kmd_easy_energy/kmd-easy-energy-card.js?v=1.3.0`):** Integrationen kopierer ikke længere dashboard-kortet ind i brugerens `/config/www/js/`-mappe (`install_frontend_card` fjernet), men serverer kortet direkte fra `frontend/` via integrationens egen HTTP-sti. Eksisterende storage-mode Lovelace-ressourcer under `/local/js/kmd-easy-energy-card.js` migreres og deduplikeres automatisk ved opstart (YAML-mode logger en opdateret advarsel med den nye URL).
- **Administratorbeskyttelse på tjenester (`async_register_admin_service`):** `configure_utility`, `reset_setup`, `update_token` og `start_mitid_sync` kræver nu Home Assistant-administratorrettigheder og valideres med eksplicitte skemaer. Vægtablets og ikke-administratorer kan fortsat synkronisere via `kmd_easy_energy.sync` (uden `mitid_username`- eller `notify_service`-felter), og dashboard-kortet skjuler opsætningsknapper (`⚙️`) for ikke-administratorer efter førstegangsopsætning.

### Rettet
- **Styrket KMD/BEOF-måleridentifikation og kundeforhold ([issue #39](https://github.com/DKAnord/fjernvarme-dk-ha/issues/39)):**
  - Rettet klassifikationsfejl i `kmd_supply.py`, så rene `MWh`- og `GJ`-varmemålere uden `m3`/`°C`-enheder eller `"Varme"`-etiket (som f.eks. Bornholms Energi & Forsyning) nu genkendes korrekt som fjernvarmemålere, og fjernet en tautologi i enhedstjekket.
  - Fjernet `"Addresses"` fra `extract_customers()` så adresseposter i KMD-profilen ikke forveksles med kundeforhold, tilføjet fallback til tokenets standard-kundeforhold hvis kundeforhold-opslag returnerer 0 målere, og udvidet `customer_identity()` / `_unit_names()` med ekstra KMD-feltnavne.
  - Ny selvforklarende, persondatafri fejltekst ved manglende varmemåler (viser fundne målerkategorier eller ukendte enheder) og øget trunkeringsgrænse (140/160 → 220 tegn) i fejlbeskeder og feedback-rapporten.

## [1.2.9] - 2026-11-26

### Tilføjet & Bekræftet
- **Albertslund Forsyning bekræftet live (KMD / Min Forsyning 2):** Markeret som ✅ **Bekræftet** efter live-verifikation via MitID (`minforsyning-2.kmd.dk`, `plant=165`), inkl. eksisterende officielle 2026/2027-takster (`0,84048 kr./kWh` årssnit inkl. moms i 2026, `0,79863 kr./kWh` i 2027 samt `±1 %/°C` afkølingstakst under `35 °C` / over `40 °C`) og opdateret kortressource (`/local/js/kmd-easy-energy-card.js?v=1.2.9`).
- **Kalundborg Forsyning bekræftet live (KMD / Min Forsyning 2):** Markeret som ✅ **Bekræftet** efter live-verifikation via MitID (`minforsyning-2.kmd.dk`, `plant=177`, `utility=1`), inkl. eksisterende officiel 2026-takst (`0,80625 kr./kWh` inkl. moms, belastningsbidrag `0,625 kr./m³`, fast arealpris `45,625 kr./m²/år` samt `±0,00375 kr./kWh/°C` ift. `45 °C`).

## [1.2.8] - 2026-11-25

### Tilføjet & Bekræftet
- **Dronninglund Fjernvarme tilføjet og bekræftet live + 2026-takst:** Tilføjet som dedikeret ✅ **Bekræftet** E|Forsyning-værk (`dronninglund-fjernvarme`, `forsyningId: 66D241DC-AE10-49F5-A176-81CC8C58BEF7`, `https://eforsyning.dk/dronninglundfjernvarme/`) efter live-verifikation, inkl. automatisk opgradering fra `eforsyning-custom` samt officiel 2026-takst fra [Tarifblad pr. 1. feb. 2026](https://dronninglundfjernvarme.dk/oekonomi-og-referater/tarifblade/aktuelt-tarifblad) (`0,81875 kr./kWh` inkl. moms, fast arealbidrag `25,00 kr./m²/år` inkl. moms, målerleje `750,00 kr./år` inkl. moms og `±1 %/°C` afkølingstarif under `30 °C` / over `40 °C`).
- **Officielle 2026/2027-takster tilføjet til 25 yderligere værker (nu 35/40 værker med indbyggede takster):** Bl.a. det bekræftede værk **Aalborg Forsyning** (`0,95625 kr./kWh`, `14,00 kr./m²/år`, `±2 %/°C`), **Galten Varmeværk**, **Struer Energi**, **Vestforsyning**, **Kalundborg Forsyning**, **Albertslund Forsyning**, **Nykøbing Sjælland Varmeværk**, **Forsyning Helsingør**, **Hjørring Varmeforsyning**, **Fjernvarme Horsens**, **Vestforbrænding**, **Egedal Fjernvarme**, **Fredericia Fjernvarme**, **Vejle Fjernvarme**, **Sønderborg Varme**, **Avedøre Fjernvarme**, **Solrød Fjernvarme**, **Thisted Varmeforsyning**, **Assens Fjernvarme**, **Ringkøbing Fjernvarme**, **Hvide Sande Fjernvarme**, **Kibæk Varmeværk**, **Kjellerup Fjernvarme**, **Ansager Varmeværk** og **Dianalund Fjernvarme**.

### Oprydning
- **Fjernet 5 ikke-fjernvarmeværker fra værklisten:** `lef`, `provas`, `skanderborg-forsyning`, `samn` og `go-energi` (leverer kun vand/spildevand/affald/el — ikke fjernvarme).

## [1.2.7] - 2026-11-25

### Tilføjet
- **Valgfrit fast arealbidrag / abonnement & forventet årsudgift ([issue #37](https://github.com/DKAnord/fjernvarme-dk-ha/issues/37)):**
  - Tilføjet valgfrie indstillinger for **fast arealbidrag inkl. moms (`fixed_fee_dkk_per_m2_year`, kr./m²/år)**, **boligareal / opvarmet areal (`heated_area_m2`, m²)** og **fast årsabonnement / målerbidrag inkl. moms (`fixed_fee_dkk_per_year`, kr./år)** under integrationens indstillinger (`⚙️`), dashboard-kortets indstillingspanel og tjenesten `kmd_easy_energy.configure_utility` (`0 = deaktiveret / standard`).
  - **Hedensted Fjernvarme** har nu indbygget officiel 2026/2027-takst for fast arealbidrag (**`33,75 kr./m²/år` inkl. moms** pr. 1. nov. 2026), som aktiveres automatisk, så snart du indtaster dit boligareal (`m²`).
  - Når et fast bidrag er konfigureret, indregnes det forholdsmæssigt i døgn-, måneds-, års- og prognosetallene (`cost_estimate` og `degree_day.forecast_annual_dkk`), og dashboard-kortet viser KPI-feltet **Forventet årsudgift** (`forecast_annual_dkk`) sammen med `/local/js/kmd-easy-energy-card.js?v=1.2.7`. Standardværdier er `0`, så eksisterende opsætninger uden areal/abonnement er uændrede.

## [1.2.6] - 2026-11-25

### Tilføjet
- **Dynamisk fremløbsafhængig afkølingstarif for Hillerød Forsyning ([issue #36](https://github.com/DKAnord/fjernvarme-dk-ha/issues/36)):**
  - Understøtter nu Hillerød Forsynings officielle 2026/2027-skema (`47 °C` ved `<= 58 °C` fremløb, faldende med `1 °C/°C` til `37 °C` ved `>= 68 °C` fremløb) automatisk ud fra målerens fremløbstemperatur (`TI` fra Watts On, m³-vægtet pr. måned og år).
  - Afkølingstariffen er nu **kun tillæg (ingen bonus)** som standard (`motivation_bonus: false`, `bonus_temp: 0.0`, `+1 %/°C` ved overskridelse af kravet).
  - Tilføjet valgfri manuel overstyring af **fremløbstemperatur (`forward_temp`)** i integrationsindstillinger (`⚙️`), dashboard-kortets indstillingspanel og tjenesten `kmd_easy_energy.configure_utility` (`0 = automatisk fra måler`).

### Rettet
- **Dashboard-kortet for værker uden bonus (`bonus_temp = 0`):** Returtemperatur-grafen og timeprofilen tegner ikke længere en `0 °C`-linje eller kollapser Y-aksen, søjler farves grønne/røde (`OK` / `Gebyr`), og nye kort via `getStubConfig()` bruger automatisk værkets egne grænser.

## [1.2.5] - 2026-11-25

### Tilføjet
- **Frederikshavn Forsyning 2026-takst ([issue #24](https://github.com/DKAnord/fjernvarme-dk-ha/issues/24)):** Indbygget officiel 2026-takst fra [forsyningen.dk/varme/priser](https://www.forsyningen.dk/varme/priser) (`873,75 kr./MWh` inkl. moms pr. 1. nov. 2026 = `0,87375 kr./kWh`; `798,75 kr./MWh` jan–okt 2026 samt `1 %/°C` motivationstarif).

### Rettet
- **Forbedret migrering af eksisterende KMD `MWh`/`GJ`-caches til `kWh` ([issue #24](https://github.com/DKAnord/fjernvarme-dk-ha/issues/24)):** Ved opgradering fra ældre versioner (før `v1.2.3`) genberegnes `Timeprofil` (`hourly.kwh`), `Døgnforbrug` (`total`, `gennemsnit`, `minimum`, `maksimum` ekskl. ufuldstændig slutdag), `Prognose` (ud fra rå `overview`-værdier når de findes) og Home Assistant Energy-statistik nu direkte ud fra de uafrundede cachede punkter ved opstart, så `0,00 kWh/t` og `0,0 kWh/d` ikke bliver hængende frem til næste MitID-synkronisering.

## [1.2.4] - 2026-11-25

### Tilføjet & Bekræftet
- **Hillerød Forsyning bekræftet live + 2026/2027-takst ([issue #34](https://github.com/DKAnord/fjernvarme-dk-ha/issues/34)):** Markeret som ✅ **Bekræftet** efter første live-verifikation på Watts On fra `@MichaelDepner`, inkl. officielle 2026/2027-takster (`0,67 kr./kWh` inkl. moms i 2026, `0,75 kr./kWh` i 2027 samt `1 %/°C` afkølingstarif fra [Hillerød Forsyning Priser & takster 2026](https://hfors.dk/selvbetjening/priser-takster-2026)).
- **Hedensted Fjernvarme tilføjet og bekræftet live + 2026/2027-takst ([issue #35](https://github.com/DKAnord/fjernvarme-dk-ha/issues/35)):** Tilføjet som dedikeret ✅ **Bekræftet** E|Forsyning-værk (`hedensted-fjernvarme`, `forsyningId: 4F2200AF-8833-4237-81D9-E5CEF34582A2`) efter live-verifikation fra `@henningpetersen` (`kWh, m3, °C`), inkl. automatisk opgradering fra `eforsyning-custom` samt officielle 2026/2027-takster (`0,93125 kr./kWh` inkl. moms pr. 1. nov. 2026 / `0,85 kr./kWh` jan–okt 2026 og `2 %/°C` motivationstarif over `40 °C` + automatisk `Forv_Retur` fra [Hedensted Fjernvarmes prisliste 2026](https://hedensted-fjernvarme.dk/oekonomi/priser)).

### Forbedret
- **Automatisk `available_units`-backfill fra eksisterende cache ([issue #34](https://github.com/DKAnord/fjernvarme-dk-ha/issues/34)):** Eksisterende Watts On- og E|Forsyning-installationer, hvis cache stammer fra før `v1.2.3`, får nu efterudfyldt `available_units` (`kWh`, `m3`, `°C`) direkte ved opstart i `_enrich_derived()` ud fra registrerede kapabiliteter og historik.

## [1.2.3] - 2026-11-24

### Tilføjet
- **Bornholms Energi & Forsyning (BEOF) bekræftet live + 2026-takst ([issue #33](https://github.com/DKAnord/fjernvarme-dk-ha/issues/33)):** Markeret som ✅ **Bekræftet** efter live-verifikation fra `@danieln431` via MitID (Min Forsyning 2), inkl. officiel 2026-takst (`0,7275 kr./kWh` inkl. moms og garantiprovision samt `±1 %/°C` afkølingsregulering fra [BEOF priser](https://beof.dk/vores-varme/priser-og-gebyrer/)).
- **Fjernvarme Fyn bekræftet live + 2026-takst ([issue #29](https://github.com/DKAnord/fjernvarme-dk-ha/issues/29)):** Markeret som ✅ **Bekræftet** efter live-verifikation fra `@PalleEngkjaer` på Watts On (`GJ`-konvertering + `MQ` fallback fra `v1.2.1`), inkl. officiel 2026-energipris (`0,5895 kr./kWh` inkl. moms = `163,75 kr./GJ` / `589,50 kr./MWh` fra [Prisfolder 2026](https://www.fjernvarmefyn.dk/media/efafmmg2/fjernvarmepriser_jan_2026.pdf)).
- **Hadsund Fjernvarme Takstblad 2026 ([issue #32](https://github.com/DKAnord/fjernvarme-dk-ha/issues/32)):** Indbygget officiel 2026-takst (`0,62938 kr./kWh` inkl. moms inkl. NOx-afgift og `±2 %/°C` motivationstarif under `30 °C` / over `40 °C` fra [Takstblad-2026.pdf](https://hadsundfjernvarme.dk/p/Hadsund%20Fjernvarme/Priser/Takstblad-2026.pdf)).

### Rettet
- **KMD-målere i `MWh` og `GJ` konverteres nu til `kWh` ([issue #33](https://github.com/DKAnord/fjernvarme-dk-ha/issues/33)):** Når et KMD-/Min Forsyning-værk (f.eks. Bornholms Energi & Forsyning) leverer varmemålerdata i `MWh` eller `GJ` i stedet for `kWh`, ganges års-, måneds-, dags-, time- og prognosetal nu automatisk med `1000` (`MWh`) eller `1 / 0,0036` (`GJ`), så både kortet, HA Energy-statistik og `kr./kWh`-beregninger vises i rigtige `kWh`. Eksisterende ukorrigerede `MWh`/`GJ`-caches migreres automatisk ved opstart.

### Forbedret
- **Hurtigere og mere kompakt HACS-installation (`kmd_easy_energy.zip`):** HACS og Home Assistant Marketplace henter nu en færdigpakket release-fil kun med selve integrationen (`custom_components/kmd_easy_energy`) via GitHubs release-CDN i stedet for hele udviklings-repoet (tests, dokumentation og byggescripts), hvilket gør installation og opdatering hurtigere og mere robust mod GitHub API rate-limits.
- **Automatisk opgradering af `eforsyning-custom` & `available_units`-rapportering ([issue #32](https://github.com/DKAnord/fjernvarme-dk-ha/issues/32)):** Eksisterende `eforsyning-custom`-opsætninger matches nu automatisk på `eforsyning_supplier_id` eller `portal_url` mod `utilities.json` (og kortets indbyggede værkliste), så de automatisk får ✅ **Bekræftet**-status, værkets standardtakster og bynavn uden genopsætning. Samtidig udfylder både `eforsyning_mapping.py` og `wattson_mapping.py` nu `available_units` (`kWh`, `m3`, `°C`), og dashboard-kortets feedback-rapport udleder enheder fra indlæste data som fallback.
- **Desktop (`>= 1280px`) & ultrawide (`>= 1600px`) dashboard-layout (`custom:kmd-easy-energy-card`):**
  - Begrænset kortets maksimale bredde (`max-width: 1480px`), rettet 3+1-ombrydning i KPI-kort og de 4 vejrkorrelerede indsigter (`.insights`) når Home Assistants sidemenu er åben på desktop, og gjort `.bn-main`-klikfladen skarp uden utilsigtede klik på tom plads.
  - Samlet alle aktive SVG-grafer i én `.grid2`: 4-grafs opsætninger uden timedata (f.eks. E|Forsyning) vises nu i et balanceret 2×2-gitter, mens 5-grafs opsætninger (KMD / Watts On) giver den 5. fuldbredde-graf (*Dagligt forbrug*) et bredt `960×220` `viewBox` med fulde dagsnumre og matchende højde på desktop.
- **Graf-læsbarhed, tema-kontrast & flydende værktøjstip:**
  - Tilføjet flydende desktop-tooltip (`#floatTip`) ved hover/fokus direkte over søjler og temperaturpunkter (ud over mobil-linjen `#tip`).
  - Forbedret kontrast i både lyst og mørkt Home Assistant-tema for aksetekster (`.ax`, `.ax-t`, `.ax-bonus`, `.ax-penalty`), tal-glorier (`.val`), kortrammer (`--ha-card-border-color`) og udeblevne linjeskift i signaturforklaringer (`.p-leg span`).
- **Indstillinger (⚙️), MitID QR/OTP & tastaturnavigation:**
  - Centreret MitID QR/OTP-boksen (`max-width: 540px`, `aria-live="polite"`), erstattet overflydende `50%`-inputpar med CSS Grid `.ob-pair`, adskilt `<label for="notifySel">` fra brugerdefineret notify-felt samt tilføjet fuld tastaturbetjening (`Enter`/`Space` på synkroniseringsbanner, `tabindex="0"` på grafelementer, `:focus-visible`-rammer, `Escape` til at lukke indstillinger og `Enter` til at gemme/starte MitID).

## [1.2.2] - 2026-11-24

### Rettet
- **Asynkron tidszone-indlæsning i KMD-synkronisering ([hacs/default#14752](https://github.com/hacs/default/pull/14752#pullrequestreview-6036764245)):** `ZoneInfo("Europe/Copenhagen")` i `coordinator.py` (`_async_fetch_from_kmd`) er erstattet med `await dt_util.async_get_time_zone("Europe/Copenhagen")`, og `zoneinfo`-importen er fjernet, så første indlæsning sker i executor uden at blokere Home Assistants event loop.
- **Hassfest-afhængighed for statisk kortsti (`manifest.json`):** Tilføjet `"http"` til `after_dependencies` i `manifest.json`, da integrationen registrerer `/local/js/kmd-easy-energy-card.js?v=1.2.2` direkte via `StaticPathConfig`.

## [1.2.1] - 2026-11-24

### Tilføjet & Bekræftet
- **Hadsund Fjernvarme tilføjet og bekræftet live (E|Forsyning):** Markeret som ✅ **Bekræftet** efter live-verifikation fra `@cokeman0` ([issue #16](https://github.com/DKAnord/fjernvarme-dk-ha/issues/16)), inkl. forudfyldt `forsyningid` (`49C73776-76BE-4382-BA5C-2B4E7384CC34`) og portal-URL (`https://eforsyning.dk/hadsundfjernvarme/`).

### Rettet
- **Watts On `MQ`-kvalitetsfilter (Fjernvarme Fyn, [issue #29](https://github.com/DKAnord/fjernvarme-dk-ha/issues/29)):** `parse_heat_items()` accepterer nu også blanke/kendte gyldige kvalitetsværdier og falder sikkert tilbage til ikke-ugyldige intervaller med `quality_fallback`-markering, når et værk ikke returnerer `"Measured"`, så alle aflæsninger ikke længere springes over som `not_measured`. Samtidig registreres de sete `MQ`-værdier (kun nøgler og antal, ingen persondata) i `wattson.quality_seen` i diagnostics.
- **Dashboard-kort på dansk Home Assistant og helt nye installationer ([issue #16](https://github.com/DKAnord/fjernvarme-dk-ha/issues/16)):** Kortet finder nu automatisk overblikssensorer med dansk endelse (`*_overblik`), suffikser (f.eks. `*_overview_2`) og omdøbte sensorer i stedet for at falde tilbage til Kredsløb/MitID-guiden. Derudover registrerer integrationen nu selve `/local/js/kmd-easy-energy-card.js?v=1.2.1` direkte via Home Assistants statiske HTTP-rute (`StaticPathConfig`), så kortet virker med det samme selv på nye installationer uden `<config>/www` ved opstart (uden en ekstra genstart).

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

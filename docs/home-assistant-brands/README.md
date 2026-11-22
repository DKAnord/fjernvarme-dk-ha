# Brand icons for home-assistant/brands

Home Assistant and HACS do **not** automatically pick up icons from
`custom_components/kmd_easy_energy/brand/` in this repository. Official
custom-integration icons are added via a pull request to
[home-assistant/brands](https://github.com/home-assistant/brands).

This folder is a ready-made tree for that PR. Opening the PR is a
maintainer decision (Daniel / @DKAnord) — nothing has been submitted.

## Proposed layout

```
custom_integrations/kmd_easy_energy/icon.png
custom_integrations/kmd_easy_energy/icon@2x.png
```

The PNG files are copies of the icons already in this repo (`icon.png` is
256×256, `icon@2x.png` is 512×512). Before opening the PR, confirm the
current brands-repo guidelines and add dark-mode variants if the checklist
now requires them.

## Suggested PR text

**Title:** Add `kmd_easy_energy` custom integration icons

**Body:** Icons for the custom integration
[DKAnord/kmd-fjernvarme-ha](https://github.com/DKAnord/kmd-fjernvarme-ha)
(domain `kmd_easy_energy`, Danish district heating on the KMD Easy Energy
platform).

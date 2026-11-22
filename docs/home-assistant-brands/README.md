# Brand icons for home-assistant/brands

Home Assistant and HACS do **not** automatically pick up icons from
`custom_components/kmd_easy_energy/brand/` in older setups, though since
February 2026 `home-assistant/brands` no longer accepts PRs for new custom
integrations — Home Assistant's Brands Proxy API serves local `brand/`
assets directly from `custom_components/<domain>/brand/`.

This folder is kept as a reference tree for the icon assets.

## Proposed layout

```
custom_integrations/kmd_easy_energy/icon.png
custom_integrations/kmd_easy_energy/icon@2x.png
```

The PNG files are copies of the icons already in this repo (`icon.png` is
256×256, `icon@2x.png` is 512×512).

## Reference description

**Title:** Add `kmd_easy_energy` custom integration icons

**Body:** Icons for the custom integration
[DKAnord/fjernvarme-dk-ha](https://github.com/DKAnord/fjernvarme-dk-ha)
(domain `kmd_easy_energy`, **Dansk Fjernvarme** — Danish district heating
for KMD Easy Energy, Watts On, and E|Forsyning).

# NEON data-product ingestion

## Sources

- `https://data.neonscience.org/api/v0/sites`: one record per site, each with a
  `dataProducts` list giving product code, title, available months, and the
  releases that contain those months. This is the site-specific evidence.
- `https://data.neonscience.org/api/v0/products`: the product catalog, used only
  for the processing level (`productCategory`) and science team. Catalog
  `siteCodes` are not used to create declarations.

Both complete responses are archived as canonical JSON, gzip-compressed with a
fixed timestamp, in `db/raw/neon/`. Most of their size is per-month download URLs.

## Snapshot of the 2026-10-25 import

- 81 sites (40 CORE, 41 GRADIENT), 6,131 site–product declarations, 156 distinct
  products out of 203 in the catalog (29 catalog products have status `FUTURE`).
- Per-site counts range from 44 (TOMB) to 92 (HARV).
- By processing level: Level 1, 4,505; Level 2, 556; Level 3, 910; Level 4, 160.
- AOP (airborne) products occur at Levels 1–3; Level 3 also has three tower
  (TIS) products. Level is therefore not a proxy for airborne collection.

## Interpretation rules

- A product is a bundle (e.g. "Soil physical and chemical properties, Megapit"
  or eddy-covariance bundles), so declarations are `UNSPECIFIED` and carry no
  primary term. BERVO crosswalks are attached by product code (see below).
- `available_years` are calendar years with at least one available month.
  `data_versions` lists only releases with months for the site.
- Data for a product at a site does not imply the product's full sampling design
  is implemented there; NEON's per-site sampling can vary.

## BERVO crosswalks (2026-10-26)

`db/curated/variable_mappings/neon_bervo.yaml` holds 122 reviewed assertions
covering 82 of 156 products (71 NARROW, 25 CLOSE, 25 BROAD, 1 RELATED; no EXACT).
Candidates were drafted from product descriptions against BERVO 2026-09-03 and
then reviewed for consistency. Conventions:

- NARROW: the target is one property within a bundled product.
- CLOSE: a single-property product matching a medium-appropriate definition.
- BROAD: a single-property product whose only fitting BERVO term is generic
  (e.g. water temperature → Temperature; BERVO has no water temperature term).
- One target per concept family across products: Total precipitation for all
  gauges, Water discharge for all discharge products, Soil organic carbon content
  for soil chemistry, Root nitrogen to carbon ratio for root chemistry.
- At most three targets per product, for its principal properties, so bundles
  such as soil characterization omit some valid components.
- EcoSIM-defined terms are used only where the definition describes an observable
  quantity in the same medium (e.g. eddy-covariance heat fluxes, fPAR).

Unmapped: organism counts, taxonomy, sequences and pathogens; imagery,
reflectance, radiance, LiDAR raw data and spectral indices; particulate matter;
nitrate in surface water and Secchi depth (no water-specific BERVO terms);
gauge height; reaeration; habitat and morphology surveys; management events.

## ENVO site classifications (2026-10-26)

Source: the NEON field site metadata export (`site_type`, `site_subtype`,
`dominant_nlcd_classes`), archived as `db/raw/neon/field-sites.json.gz`.
`db/curated/classification_mappings/neon.yaml` has 18 assertions:

- 10 NLCD classes → ENVO "area of …" land-cover zones, origin SOURCE: ENVO
  v2026-06-26 carries `xref: NLCD:nn` on each, and the MRLC legend gives the code
  for NEON's class names. ENVO does not assert NLCD's cover thresholds (CLOSE).
- Core/Gradient Terrestrial → terrestrial ecosystem (RELATED; a NEON design
  class is not itself an ecosystem). Core/Gradient Aquatic are left unmapped,
  because the subtype gives a more specific ecosystem.
- Wadeable Stream → site type stream (BROAD) and freshwater stream ecosystem.
  Non-wadeable River → river (BROAD) and freshwater river biome. Lake → lake
  (CLOSE) and freshwater lake biome. NEON describes all 34 aquatic sites as
  freshwater. ENVO has no freshwater lake or river ecosystem class separate from
  these biomes.

Result: all 81 sites have ecosystem and land-cover terms; the 34 aquatic sites
have a site type. NEON's page counts 24 wadeable streams and 3 non-wadeable
rivers, whereas the export lists 23 and 4; the export is used. NLCD classes are
not converted into forest, grassland, or wetland ecosystem terms. That would be
an inference beyond the source and remains a curation option.

## Open questions

- Product-level variables files (`/products/{code}` specs and downloadable
  `variables.csv`) would give field-level names and units for crosswalks.
- Whether to merge NEON, DEIMS, and AmeriFlux (`US-x**`) records for the same
  physical site, or link them through an explicit same-site crosswalk.
- Field-level crosswalks from each product's variables file would replace the
  product-level BERVO approximations.

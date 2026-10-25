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
  ontology term. Mapping to BERVO needs per-product review, ideally at the level
  of the variables in each product's published variables file.
- `available_years` are calendar years with at least one available month.
  `data_versions` lists only releases with months for the site.
- Data for a product at a site does not imply the product's full sampling design
  is implemented there; NEON's per-site sampling can vary.

## Open questions

- Product-level variables files (`/products/{code}` specs and downloadable
  `variables.csv`) would give field-level names and units for crosswalks.
- Whether to merge NEON, DEIMS, and AmeriFlux (`US-x**`) records for the same
  physical site, or link them through an explicit same-site crosswalk.
- ENVO ecosystem characterization of NEON sites remains to be curated separately
  from facility type and from these product declarations.

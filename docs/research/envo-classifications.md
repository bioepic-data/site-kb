# ENVO classifications beyond NEON

Added 2026-11-06. Sources are kept verbatim as `source_classifications` and
mapped by curated crosswalks in `db/curated/classification_mappings/`, the same
mechanism as the NEON crosswalk (see `neon-ingestion.md`). ENVO is pinned to
v2026-06-26.

## Coverage

| Network | Sites | With ENVO ecosystem | With ENVO land cover |
| --- | ---: | ---: | ---: |
| NEON (merged with DEIMS) | 81 | 81 | 81 |
| AmeriFlux | 849 | 0 | 849 |
| DEIMS | 1,318 | 1,043 | 319 |
| NGEE and other curated sites | 36 | 0 | 0 |

1,973 of 2,284 sites have at least one ENVO term. DEIMS records without one have
no environmental classification or only unmapped values. The 36 curated sites
have no source classification field; their terms need per-site curation with
evidence.

## AmeriFlux IGBP (17 codes, `ameriflux.yaml`)

IGBP is a land-cover legend, so codes map to ENVO land-cover zones, not
ecosystems. ENVO has no IGBP cross-references (unlike NLCD), so all assertions
are curated against the FLUXNET IGBP legend. Leaf type and canopy density are
not represented in ENVO, so ENF/EBF/DNF/DBF and CSH/OSH map BROAD to the
evergreen/deciduous forest and scrub areas. CVM (cropland/natural vegetation
mosaic) is RELATED to cropland.

## DEIMS environmental characteristics (79 values, `deims.yaml`)

- `geoBonBiome` (5) and `biome` (18) are DEIMS controlled lists; `ecosystemType`
  (45) mixes WWF terrestrial biomes, FEOW freshwater habitat types, marine
  types, and simple labels.
- WWF compound classes map BROAD to their shared ENVO parent (e.g. temperate,
  montane, or Mediterranean biome; broadleaf or coniferous forest biome).
- Plain "Lakes"/"Rivers" and EUNIS "Inland surface waters" map BROAD to aquatic
  biome; freshwater is asserted only for explicitly freshwater classes.
- Deciduous, evergreen, and mixed forest classes also add the matching ENVO
  land-cover zone.
- Deliberately unmapped: "Coastal" in every scheme (no ENVO coastal ecosystem or
  biome), EUNIS top-level classes B, E, F, G, H and X (each spans several ENVO
  ecosystems), and EUNIS levels below the top level (337 values in all).

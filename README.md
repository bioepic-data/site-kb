# site-kb

Environmental Research Site Knowledge Base — a unified registry of sites across DEIMS/LTER, NEON, ARM, AmeriFlux, and other networks, with harmonized variable/measurement metadata and ontology bindings.

## Setup

```bash
uv sync --group dev
```

## Usage

```bash
# Refresh imported metadata (leaves curation untouched)
just fetch-deims --limit 10
just fetch-neon
just fetch-ameriflux
just fetch-ameriflux-variables --refresh

# Assemble and validate
just validate-db
just validate-terms
```

## Data layers

| Path | Purpose | Edit manually? |
| --- | --- | --- |
| `db/raw/deims/` | Complete source JSON snapshots with retrieval timestamps | No |
| `db/raw/ameriflux/` | Per-site source snapshots, complete API responses, import report, and locally supplied BIF originals | No |
| `db/raw/ameriflux/variables/` | v2 site inventories, FP definitions, and compressed current BASE coverage responses | No |
| `db/raw/neon/` | Compressed complete NEON `/sites` and `/products` responses with retrieval timestamps and checksums | No |
| `db/imported/deims/`, `db/imported/neon/` | Source-specific metadata normalized by importers; tracked in Git | No: refresh can overwrite these files |
| `db/imported/ameriflux/` | AmeriFlux site metadata normalized from the public site API | No: refresh can overwrite these files |
| `db/staged/ameriflux/bif/` | Reconstructed BIF groups for review; excluded from site assembly | No: regenerate from raw BIF inputs |
| `db/curated/sites/` | Complete, independently curated site records | Yes |
| `db/curated/variable_mappings/` | Reusable source-to-ontology mapping assertions | Yes |
| `db/curated/overrides/` | Partial corrections/enrichment targeting existing site IDs | Yes |
| `db/sites/sites.yaml` | Assembled SiteCollection; generated and Git-ignored | No: rebuild with `just build-db` |
| `docs/research/` | Evidence, source links, and unresolved research questions | Yes |

Imported records are normalized snapshots. Full DEIMS JSON responses are separately
archived in `db/raw/deims/`, including fields our schema does not yet model.
The build reads imported site YAML, adds curated sites, applies reusable variable
crosswalks by `(source, source_id)`, then applies overrides by exact site `id`. It produces a single collection sorted by ID. Duplicate IDs
within an input layer, collisions between imported and curated sites, and
overrides targeting absent sites are errors. It does not reconcile different
IDs representing the same physical site.

Override files use the same `sites` wrapper but may omit required fields other
than `id`. For example, `db/curated/overrides/neon_abby.yaml` could contain:

```yaml
sites:
  - id: site_kb:neon-abby
    aliases:
      - Abby Road
    notes: Curated context with a source URL goes here.
```

Mappings merge recursively, scalars replace previous values, and **lists replace
the entire list** (including variables and network registrations). Preserve any
existing list entries you still need. `null` removes a field; `[]` clears a list.
An override may target either an imported or a curated site. Put standalone new
sites in `db/curated/sites/`, not in overrides. Validate partial overrides through
the assembled result using `just validate-db`, rather than as complete Sites.

`just build-db` assembles without full schema validation; `just validate-db`
rebuilds and validates. `just validate-terms` also rebuilds before checking data
ontology bindings. Neither validation checks the factual correctness of claims.
Fetch commands update matching source files but do not prune old records absent
from an API response; review deletions explicitly. In particular, a limited DEIMS
fetch is an incremental refresh. DEIMS IDs currently depend on site names, so
source renames require review of IDs and corresponding overrides.

## Normalization and observed properties

Structural normalization happens in `deims_to_site()` and `neon_to_site()` in
`src/site_kb/scripts/fetch_*.py`. DEIMS now supports WKT point coordinates and
imports `attributes.focusDesignScale.observedProperties` from its full JSON.

### NEON data products

`just fetch-neon` archives the complete NEON `/sites` and `/products` API responses
in `db/raw/neon/` and imports one variable declaration per data product that the
NEON API lists for a site, with its product code (`data_product` and `source_id`),
verbatim title, processing level, calendar years with at least one available month,
and the releases (e.g. `RELEASE-2026`, `PROVISIONAL`) that contain those months.
Use `just fetch-neon --offline` to regenerate imported records from the archive.

A NEON data product often bundles several measured, derived, and quality-control
fields, so declarations are `UNSPECIFIED` and no ontology term is assigned. Products
whose description names the Airborne Observation Platform (AOP) are remote-sensing
surveys over the site, not in-situ measurements. Product availability is not evidence of continuous collection. NEON,
DEIMS, and AmeriFlux records for the same physical site keep separate IDs. See
`docs/research/neon-ingestion.md`.

### AmeriFlux site metadata and BIF staging

`just fetch-ameriflux` imports the public AmeriFlux site list without an account.
It preserves source site codes and names, uses code-based local IDs, and imports
coordinates, elevation, country, and state/province. `USA` is normalized to
`United States`; the original country and state values remain in raw snapshots.
IGBP codes, climate summaries, and reported flux-measurement years are retained
as attributed notes. They do not imply facility types, ontology mappings,
establishment/closure dates, or operational status. Site-specific variables are
imported separately by `just fetch-ameriflux-variables` from the current public v2
API. An ordinary metadata refresh replays those archived variable sources, so it
does not erase previously imported declarations.

```bash
# Select specific sites (repeat --site-id); IDs are case-sensitive
just fetch-ameriflux --site-id US-Ha1 --site-id US-xAB
just fetch-ameriflux --limit 10 --summary-only
just fetch-ameriflux --refresh-existing

# Fetch current site-reported fluxes, BASE variables, and coverage
just fetch-ameriflux-variables --refresh
# Resume a previous fetch, reusing successful cached requests
just fetch-ameriflux-variables
# Regenerate from the completed request cache without HTTP
just fetch-ameriflux-variables --offline

# Replay a complete archived API response without HTTP
just fetch-ameriflux --from-snapshot db/raw/ameriflux/responses/<sha256>.json

# Reconstruct a locally supplied BADM/BIF CSV or workbook for review
just stage-ameriflux-bif /path/to/AMF_SITE_BIF_VERSION.xlsx
```

The importer validates the selected batch before writing, preserves existing
local IDs and filenames, and atomically replaces individual files. This is not a
filesystem transaction across the whole batch; rerun from the archived response
after an interrupted write. Refresh never deletes sites absent upstream.
Raw per-site JSON includes the original record, API URL, JSON Pointer into the
response, retrieval timestamp, and response checksum. Complete responses are
archived under `db/raw/ameriflux/responses/`; checksums cover canonical JSON record
arrays, not HTTP transfer bytes. Replays preserve source retrieval timestamps.
The browser links imported YAML and per-site raw JSON.

The variable importer uses `site_info_display/AmeriFlux`, `fp_var`, and
`flux_met_variable_coverage/{site_id}` under the public v2 API. BADM flux
declarations remain distinct from specific published BASE variables. For example,
a reported CO2 flux is not the BASE `CO2` concentration variable; they use separate
source namespaces (`AMERIFLUX_BADM_SGI` and `AMERIFLUX_BASE`) while preserving the
original codes and names. Repeated BADM labels are represented once, with the
complete original lists retained in raw snapshots. `Other` and other broad flux
declarations retain unclassified granularity.

BASE entries require positive reported coverage in at least one year when
coverage is available. Gap-filled and unfilled variants are separate entries;
source qualifiers, publication versions, years with data, and HH/HR resolution
are retained. `PRODUCTS` variables are identified as derived. Other BASE variables
may be measured or computed; absence of a gap-filling qualifier is not evidence
of direct measurement. Units are copied from the FP definitions without conversion
or ontology assignment. Quality flags, footprint diagnostics, and timekeeping
columns are preserved in the archives but excluded from property declarations.

The variable fetch uses four concurrent requests with bounded retries and a
resumable `.cache/ameriflux-variables/` directory. Use `--refresh` for current data;
the default reuses completed cache files. Source retrieval times are retained.
Full v2 responses and per-site coverage are archived by canonical JSON checksum,
with gzip compression for large responses. A failed coverage request is reported
explicitly and falls back to the site-specific BASE inventory without inventing
gap-filling flags or variable-specific years. The report in
`db/raw/ameriflux/variables/import-report.json` records exclusions and failures.
All selected responses are validated before imported YAML is replaced.

`db/raw/ameriflux/import-report.json` records the latest selection, missing
existing codes, and possible overlaps with other imported sites. Candidate
matches use NEON codes in AmeriFlux names or coordinates within 100 m. They are
unreviewed, do not merge sites, and are not an exhaustive identity crosswalk.
Consequently, the browser can contain separate records for the same physical
site across networks. A partial refresh reports only its selected sites' overlaps.

BIF workbook staging is an additional route for richer observations and management
events. It preserves `(SITE_ID, VARIABLE_GROUP, GROUP_ID)`, all source rows,
repeated values, units, comments, depths, and date qualifiers. Observation/event
classification is independent of date availability; unknown groups remain
unclassified. Parsed dates retain year/month precision. Originals are archived
by byte checksum; CSV text values retain whitespace and Excel cells retain their
read values, while the original workbook preserves formatting and cell types.
Workbooks default to the `AMF-BIF` sheet; use `--sheet` for another explicit sheet.
Formula cells are rejected. Staging does not download restricted data, apply
model defaults, or itself populate `Site.variables`. The v2 importer above does
populate site declarations. Source URLs can be supplied to BIF staging with
`--source-url`; the archive timestamp is not an upstream modification time.

See [AmeriFlux ingestion and BIF review](docs/research/ameriflux-ingestion.md)
for sources, the ecosim-agent parser audit, and remaining enrichment work.

Each DEIMS declaration preserves its original name and URI in `source_variables`,
along with registry, vocabulary, JSON record URL and field pointer, retrieval time,
and source modification time. The URI is the source identity, not an assertion of
BERVO equivalence. Source labels are preserved verbatim rather than treated as
validated canonical ontology labels.

DEIMS mixes individual properties and broad parameter groups without distinguishing
them in this JSON list. Its declarations therefore have `declaration_kind:
UNSPECIFIED`. Curators can set `PROPERTY` or `PARAMETER_GROUP` when supported by
vocabulary evidence. The UI calls these property declarations rather than counting
every entry as a specific measurement. Units and intervals remain absent unless
supplied by evidence; site climate summaries are not measurement declarations.

Refresh the currently imported DEIMS records without adding the whole registry:

```bash
just fetch-deims --refresh-existing
just site
```

This preserves local IDs and filenames even if upstream site names change. Full
responses and retrieval metadata are stored in `db/raw/deims/`. Regular list-based
imports still derive IDs from names; use `--refresh-existing` for existing records.
HTTP-success responses containing API error objects are rejected.

### Source crosswalks and BERVO mappings

`Variable.mappings` holds separately attributed assertions: source registry and ID,
optional source label, target ontology ID and label, mapping relation, origin, and
evidence URLs. Optional attribution, assertion date, and notes capture rationale.
`origin: SOURCE` distinguishes an upstream crosswalk from `origin: CURATED` for our
mapping. Both assertions can be retained when they disagree. Relations are directed
source → target: `EXACT`, `CLOSE`, `BROAD` (target broader), `NARROW` (target narrower),
and `RELATED`.

Reviewed mappings in `db/curated/variable_mappings/*.yaml` use the
`VariableMappingCollection` schema. Assembly adds them to all matching source IDs
before site overrides, without changing names/IDs or inferring a primary `term`.
The existing `term` remains an explicitly selected canonical concept; legacy
`network_variable_id` and `additional_terms` still work. See the
[crosswalk authoring guide](db/curated/variable_mappings/README.md).

No BERVO equivalences have been asserted in this import: DEIMS supplies EnvThes
identities, not verified BERVO mappings. Crosswalk target labels can be checked
with `just validate-terms`; source names are intentionally not ontology-validated.
`just validate-db` validates both reusable mappings and assembled sites. Neither
validation establishes whether a mapping is scientifically correct. Unit conversion
and automatic classification of property groups remain unimplemented.

## Static database browser

`just site` assembles and validates the database, then renders a custom HTML/CSS/JS
directory into the Git-ignored `site/` folder. No MkDocs or Node packages are
required to build it. `just preview` serves it at http://127.0.0.1:8879; an optional
port can be supplied, for example `just preview 9000`.

The browser provides full-text search, network/country/origin filters, a filter
for documented variables, and a permanent page for every site. Detail pages show
measurements and ontology links, source registrations, notes, contacts, and the
imported/curated YAML, crosswalk files, and archived DEIMS JSON used for each record. All links are relative, so the
same output works under a GitHub Pages repository subpath. Search state is stored
in the URL. Pages and downloads remain usable without JavaScript; filters require
it. Missing metadata is shown explicitly, with no inferred locations or mappings.

The build copies its public input YAML to `site/sources/` and exports the assembled
collection to `site/data/sites.json`. Do not put private material in these inputs.
The renderer refreshes only an output directory carrying its generated marker;
it refuses to replace an unrecognized directory. Raw research notes remain in
`docs/research/`; evidence URLs from site records are linked in the browser.

### GitHub Pages

The workflow `.github/workflows/pages.yml` tests, validates, and builds on pull
requests and pushes to `main`. It checks schema and Python model generation,
runs the full Python and JavaScript suites, accepts valid examples and rejects
counterexamples, validates assembled data, ontology terms, and evidence quotations,
and renders the browser. Schema lint errors fail the build; existing documentation
and naming warnings remain visible without blocking it. Run `just test` and
`just lint` for the schema/model, Python, example, and lint checks locally.
Deployment is opt-in via the repository variable
`ENABLE_PAGES=true` and only runs from `main`. To enable publication, configure
**Settings → Pages → Source → GitHub Actions**, set that Actions variable, and
push the source changes. Repository privacy alone does not make a Pages site private. `just deploy` can trigger the
installed workflow on `main` using the GitHub CLI; it publishes committed remote
source, not local changes. No API ingestion runs during deployment: builds use
the reviewed, version-controlled imported and curated records.

Run renderer tests with `uv run pytest -q` and client filtering tests with
`node --test tests/web.test.cjs`. The latter use Node's built-in test runner;
Node is needed only for those tests, not for the browser build or hosting.

## Facility classification and standards-derived candidate profiles

`Site.site_type` is the high-level physical site/facility classification, preferably
ENVO. It is separate from `ecosystem_terms` and from research/observation roles.
ROPEC is classified as a wastewater treatment plant; other site types are left
unset until curated.

`db/profiles/wastewater_sludge.yaml` contains MIxS-derived **candidate** metadata:
40 wastewater/sludge fields, eight supplemental water-chemistry fields, and
applicability notes for sediment and built-environment sampling. It does not add
those measurements to any site. See [the research note](docs/research/mixs-wastewater.md)
for scope, identifiers, and the inconsistent preferred unit on `efficiency_percent`.

**Always run `linkml-term-validator` for changes involving terms.** `just
validate-terms` checks schema meanings, profiles, crosswalks, and assembled records
using explicit bindings on every ontology-term field. `just site` and CI enforce
this too. ENVO, MIxS, and SKOS validation sources are pinned/checksummed and prepared
under `cache/ontologies/`; MIxS and SKOS label indexes come from upstream RDF.
Checks validate identifiers and canonical labels; they do not establish scientific
mapping equivalence or the validity of unit annotations. Raw upstream source names
remain preserved verbatim outside canonical term-label fields.

## Shared catalog, applicability, and site evidence

`db/curated/variables/*.yaml` is the reusable **variable definition catalog**.
Each definition has a stable local `id`, a name, optional source identities and
reviewed ontology mappings (including BERVO when justified). MIxS field IDs are
preserved as MIxS terms; a MIxS metadata slot is not automatically equivalent to a
BERVO observed property.

Two independent relationships reference these definitions through `variable_id`:

- `MeasurementProfile.candidates`: potentially applicable fields. `applies_to`
  and `applicability_scope` distinguish facility, ecosystem and sample-material
  applicability. Source version, requiredness, range and cardinality describe the
  standard's submission field, not a site's measurement protocol.
- `Site.variables`: documented collection or analysis. Study-specific `evidence`,
  `method`, `sample_context`, `sampling_period` and verbatim `reported_units` stay
  on this declaration. An analytical result such as MAG completeness describes
  the recovered genome, not the wastewater itself.

Assembly resolves catalog references after site overrides, rejects unknown IDs,
conflicting shared fields and duplicate definitions, and applies reviewed source
crosswalks. It includes definitions and profiles in the assembled collection;
expanded site declarations retain their `variable_id`. Profiles never populate
site variables. The browser has a **Variables & profiles** page and displays
study context and dataset availability on site pages.

The curated wastewater records and MIxS profiles use shared definitions. Existing
DEIMS imports retain their source-shaped embedded declarations and provenance;
they are not automatically collapsed by similar labels. Reviewed source-ID
crosswalks continue to apply to these imports. NEON data products are imported
per site but not yet mapped to BERVO. No BERVO equivalences were inferred during this change.

`Site.datasets` records assay, accession, source evidence and availability
(`PUBLIC`, `ON_REQUEST`, `UNRESOLVED`). Targeted ARG/16S panels, shotgun metagenomes
and metatranscriptomes must remain distinguishable. Location can record a country
without inventing coordinates. See [treatment-site research](docs/research/wastewater-metagenomics.md)
for the seed-paper audit and the newly curated plants.

## NGEE sites

`db/curated/sites/ngee_arctic.yaml` and `ngee_tropics.yaml` contain 18 reviewed
NGEE field-site records: seven Arctic locations and eleven named Tropics sites.
They are curated from the projects' location pages and Phase 2 field overview,
with source identities and evidence URLs retained in each record. The networks
are represented separately as `NGEE_ARCTIC` and `NGEE_TROPICS`.

This is a curated import, not an API refresh. No site measurement declarations
or current operational status are inferred from project membership. Five
Tropics records have coordinates from the cited Phase 2 proposal, with original
notation, page anchors, and explicit degree-minute conversions where needed.
The remaining locations retain verified country/region metadata without guessed
points. Overlaps with broader DEIMS locations are documented without asserting
exact equivalence. See [NGEE scope and evidence](docs/research/ngee-sites.md).

Rebuild and validate with `just site`; edit these curated inputs to update them.

Curated `Site.evidence` entries identify the fields they support using JSON
Pointers (for example `/location/latitude`), alongside `source_url`, `source_label`,
`locator`, optional `quotation`, `accessed_on`, and interpretation `notes`.
Assembly rejects references to absent fields. The browser places numbered
citations beside location values and shows source excerpts in an evidence panel.
State coordinate conversions and spatial scope explicitly; record
`location.coordinate_datum` only when the source supplies it. Existing imported
coordinates without this evidence remain visible with their provenance gap
marked; the new evidence model does not retroactively verify those coordinates.

## Reference validation

`just validate-references` rebuilds the collection and runs
`linkml-reference-validator` against quotations in `Site.evidence`. It is also
required by `just site` and the Pages CI workflow. The schema marks `source_url`
as `linkml:authoritative_reference` and `quotation` as `linkml:excerpt`.
`source_label` is a curator-written display label, not an exact bibliographic
source title.

Fetched public source text is committed under `references_cache/`, following the
[mechmaker workflow](https://github.com/monarch-initiative/mechmaker/blob/main/template/justfile.jinja).
The validator uses the reviewed cached text without silently refreshing it. A
missing cache entry may be fetched; unavailable sources and unsupported prefixes
are errors, never skips. To fetch and inspect a new source:

```bash
just fetch-reference 'https://example.org/source.pdf'
# Explicitly refresh a source when reviewing upstream changes:
just fetch-reference 'https://example.org/source.pdf' --no-cache
just validate-references
```

Never write reference-cache text from the quotation being tested. Review fetched
text and cache diffs before committing them. The validator normalizes formatting
for substring matching; it does not verify the locator, coordinate conversion,
spatial equivalence, or whether an excerpt supports the scientific claim.

The NGEE import currently has **five automatically checked quotations**. Evidence
entries without a quotation remain source citations and are labeled accordingly
in HTML; a successful run does not mean those claims were checked. Tests assert
the five comparisons actually occur offline and that a fabricated quotation and
an unavailable source fail. Term checks remain a separate required validation.

## BERVO harmonization

Reviewed BERVO assertions live in `db/curated/variable_mappings/bervo.yaml`.
They match preserved upstream source IDs or local catalog definition IDs
(`source: site-kb`). Exact, close and broader mappings remain distinct; assembly
does not replace source names or automatically choose primary ontology terms.
The Variables & profiles browser groups annotations by BERVO target and exposes
unmapped definitions, with a downloadable `data/bervo.json` index.

The validator uses a checksum-pinned BERVO release with its canonical labels.
Run `just site` to validate mappings and regenerate the browser. See the
[BERVO integration notes](docs/research/bervo-integration.md) for the approach
adapted from `nmdc-sfas-brcs`, the initial mappings and remaining coverage gaps.

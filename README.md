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

# Assemble and validate
just validate-db
just validate-terms
```

## Data layers

| Path | Purpose | Edit manually? |
| --- | --- | --- |
| `db/raw/deims/` | Complete source JSON snapshots with retrieval timestamps | No |
| `db/imported/deims/`, `db/imported/neon/` | Source-specific metadata normalized by importers; tracked in Git | No: refresh can overwrite these files |
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
NEON measured-variable ingestion is still pending.

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
requests and pushes to `main`. Deployment is opt-in via the repository variable
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
crosswalks continue to apply to these imports. NEON variable coverage remains a
separate ingestion gap. No BERVO equivalences were inferred during this change.

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
Pointers (for example `/location/latitude`), alongside `source_url`, `title`,
`locator`, optional `quotation`, `accessed_on`, and interpretation `notes`.
Assembly rejects references to absent fields. The browser places numbered
citations beside location values and shows source excerpts in an evidence panel.
State coordinate conversions and spatial scope explicitly; record
`location.coordinate_datum` only when the source supplies it. Existing imported
coordinates without this evidence remain visible with their provenance gap
marked; the new evidence model does not retroactively verify those coordinates.

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

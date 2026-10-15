# AmeriFlux ingestion and BIF review

The public site API supports a reproducible baseline import of AmeriFlux site
metadata. Rich BADM/BIF data are staged separately for review before they can
support site-specific measurement declarations. No ontology equivalences or
facility classifications are inferred by either importer.

## Sources and field semantics

The initial API investigation on 2026-10-15 returned 849 unique sites from
[site_display/AmeriFlux](https://amfcdn.lbl.gov/api/v1/site_display/AmeriFlux).
The complete response and actual retrieval time are retained under
`db/raw/ameriflux/responses/`. Counts describe that response, not a fixed network
size. The endpoint is also used by
[amerifluxr](https://github.com/chuhousen/amerifluxr/blob/master/R/helper_functions.R).

| Source field | Import treatment |
| --- | --- |
| `SITE_ID` | Preserve case in the AMERIFLUX registration; lowercase only for stable local IDs and YAML filenames |
| `SITE_NAME`, `URL_AMERIFLUX` | Preserve name and source registration URL |
| `GRP_LOCATION` | Parse finite numbers without losing signs or zero values; enforce latitude/longitude bounds |
| `COUNTRY`, `STATE` | Normalize USA to United States; preserve source administrative codes otherwise |
| `IGBP` | Source vegetation code in notes, separate from site/facility classification |
| `GRP_CLIM_AVG` | Source climate context in notes, not measurement declarations |
| `TOWER_BEGAN`, `TOWER_END` | Reported flux-measurement years in notes, not dates of site establishment or closure |

Missing fields remain absent. Invalid numeric values, nonfinite values, and the
`-9999` sentinel in location fields stop the selected import rather than becoming
coordinates or elevations. Negative elevation is valid. A missing tower end year
does not establish current operational status; the
[AmeriFlux status definitions](https://ameriflux.lbl.gov/sites/site-status-definition-for-service-eligibility/)
distinguish operation, publication activity, and team responsiveness.

The public site-list response does not include site-specific variable inventories,
contacts, dataset DOIs, or explicit cross-network identifiers. These need richer
sources. The [BADM overview](https://ameriflux.lbl.gov/data/badm/) describes site
metadata, biological/ecological observations, and disturbance information. Full
BIF downloads have account/data-policy requirements documented by
[amerifluxr](https://github.com/chuhousen/amerifluxr). This importer performs only
public site-list retrieval; BIF staging accepts an already obtained local file.

## Identity and overlap review

Local IDs use `site_kb:ameriflux-<lowercase SITE_ID>` and survive upstream renames.
Refresh also preserves any pre-existing local ID and filename. Duplicate upstream
IDs, case collisions, and conflicting output identities are errors.

AmeriFlux `US-xAB` names NEON Abby Road (ABBY), whose coordinates agree closely
with the existing `site_kb:neon-abby` record. The generated import report records
this and other candidate overlaps, with the matching evidence. Nearby towers can
still be distinct observation sites; proximity alone must not trigger merging.
Candidates remain separate records until a reviewed cross-network identity
crosswalk and explicit assembly policy are implemented. The report compares
other imported records, not curated sites, and does not establish completeness.

## ecosim-agent audit

The reviewed upstream revision is
[`0b518e04f10167dcc6ddb92d3d0b2eb1f5ef2e87`](https://github.com/bioepic-data/ecosim-agent/tree/0b518e04f10167dcc6ddb92d3d0b2eb1f5ef2e87/.agents/skills).
The implementation here is independently written, using its documented BIF
grouping conventions and extraction lessons; it does not vendor the EcoSIM tools.

- [Site info](https://github.com/bioepic-data/ecosim-agent/blob/0b518e04f10167dcc6ddb92d3d0b2eb1f5ef2e87/.agents/skills/ameriflux-site-info/SKILL.md)
  documents sign-loss bugs affecting southern latitude, negative temperature,
  and below-sea-level elevation. Regression tests cover those cases. The API
  remains the primary source here; country envelopes and climate plausibility
  checks do not replace source values.
- [BIF sorter](https://github.com/bioepic-data/ecosim-agent/blob/0b518e04f10167dcc6ddb92d3d0b2eb1f5ef2e87/.agents/skills/ameriflux-bif-timeseries-sorter/scripts/sort_bif_timeseries.py)
  groups rows by site, variable group, and group ID. Its implementation joins
  repeated values into delimited strings, classifies undated records as static,
  and can choose an unrelated unit field as a fallback. Our parser retains all
  rows and repeated values, classifies known groups independently of dates, and
  makes no unit assignments or conversions.
- [BIF management](https://github.com/bioepic-data/ecosim-agent/blob/0b518e04f10167dcc6ddb92d3d0b2eb1f5ef2e87/.agents/skills/ameriflux-bif-ecosim-mgmt/SKILL.md)
  identifies management information in comments. Its crop codes and default
  planting, fertilizer, tillage, and harvest parameters are model assumptions
  and are not imported into the knowledge base.
- [Unified extractor](https://github.com/bioepic-data/ecosim-agent/blob/0b518e04f10167dcc6ddb92d3d0b2eb1f5ef2e87/.agents/skills/unified-ameriflux-extractor/SKILL.md)
  suggests future NADP, tDEP, and gSSURGO enrichment. Such spatial associations
  need separate provenance and cannot be represented as measurements made by
  the AmeriFlux site.

## BIF staging contract

`parse_ameriflux_bif.py` accepts CSV, XLSX, and XLSM. Each staged group retains
the original site/group identifiers, a list of values for each verbatim variable
name, and every input row with its source row number and extra columns. Source
identity is scoped to the archived file checksum and sheet as well as the group
key; group IDs are not assumed stable across releases.

Known biological/soil observation groups are marked `OBSERVATION`; `GRP_DM_*`
groups are marked `MANAGEMENT_EVENT`; a small allowlist covers metadata groups.
Other groups are `UNCLASSIFIED`. These classifications guide review and do not
create `Site.variables`. Date status is recorded separately, so an undated
observation remains an observation. `_DATE_UNC` is preserved as a qualifier,
never substituted for an observation date. Invalid dates remain visible with
review issues; year/month-only values never acquire invented days.

No observed values, units, comments, or qualifiers are converted to ontology
annotations during staging. When declarations are curated later, preserve names
and IDs in `SourceVariable`, reference the archived group and source URL, and
validate ontology targets separately with `linkml-term-validator`.

## Remaining enrichment work

1. Review cross-network identity candidates and implement explicit reconciliation.
2. Obtain versioned BIF files through the appropriate account and policy workflow;
   exercise staging against those releases. Current BIF tests use synthetic CSV
   and Excel fixtures, not a downloaded production BIF workbook.
3. Review group-specific semantics before promoting source records to site
   declarations. Contacts, ecosystem context, management events, and biological
   measurements need distinct treatment. Extend the schema only where justified.
4. Add product-specific dataset availability and variable inventories with source
   versions and measurement periods. Distinguish direct measurements, gap-filled
   series, and derived products; the existence of a standard variable is not
   evidence of its availability at a site.
5. Curate IGBP ecosystem and variable ontology crosswalks with evidence, explicit
   mapping relations, canonical-label validation, and no inferred primary terms.

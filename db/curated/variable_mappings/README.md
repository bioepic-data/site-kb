# Reusable variable crosswalks

Put reviewed assertions in `*.yaml` files with a `mappings` list, conforming to
`VariableMappingCollection` in the LinkML schema. Each assertion requires:

- `source`: registry name (e.g. `DEIMS`).
- `source_id`: exact source ID/URI, including its original HTTP/HTTPS spelling.
- `target`: ontology `id` and `label`, preferably a verified BERVO concept.
- `relation`: `EXACT`, `CLOSE`, `BROAD`, `NARROW`, or `RELATED`.
- `origin`: `CURATED` for our assertions; `SOURCE` for an attributed upstream crosswalk.
- `evidence`: nonempty list of URLs supporting the mapping assertion.

Optional `source_name`, `attributed_to`, `asserted_on`, and `notes` preserve the
label, responsible party, assertion date, and rationale. Direction is always
source → target: BROAD means the target is broader, NARROW means it is narrower.

Assembly applies these assertions to every matching `(source, source_id)` before
site-specific overrides. They supplement source-supplied mappings and do not
rewrite source names/IDs, classify declaration granularity, or populate the
curator-selected primary `term`. Lists in site overrides still replace whole
lists, so an override of `variables` also replaces their assembled mappings.

No BERVO crosswalk is seeded yet: the DEIMS JSON supplies EnvThes identity, not
BERVO equivalence. Add mappings only after verifying target concepts and relations.
Run `just validate-db` and `just validate-terms` after editing.

Mappings with `source: site-kb` and `source_id: site_kb:variable-…` target a
shared catalog definition directly. They propagate to referencing declarations
without inventing an upstream source identity. `bervo.yaml` supplies the first
reviewed BERVO set, including explicit provisional CLOSE and broader matches.
See `docs/research/bervo-integration.md` for source pinning and review limits.
`neon_bervo.yaml` maps NEON data product codes; see `docs/research/neon-ingestion.md`
for its relation conventions and the products left unmapped.

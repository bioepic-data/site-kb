## Project-specific recipes. Imported by the main justfile.

# Assemble imported records and curated additions/overrides
build-db:
  uv run python -m site_kb.scripts.build_db

# Build and preview the static database browser
preview PORT="8879": site
  uv run python -m http.server {{PORT}} --bind 127.0.0.1 --directory site

# Rebuild and validate all assembled site YAML files against the schema
validate-db: build-db
  @for f in db/profiles/*.yaml; do \
    [ -f "$f" ] || continue; \
    uv run linkml-validate -s src/site_kb/schema/site_kb.yaml -C MeasurementProfileCollection "$f" || exit 1; \
  done
  @for f in db/curated/variable_mappings/*.yaml; do \
    [ -f "$f" ] || continue; \
    uv run linkml-validate -s src/site_kb/schema/site_kb.yaml -C VariableMappingCollection "$f" || exit 1; \
  done
  @for f in db/sites/*.yaml; do \
    echo "Validating $f..."; \
    uv run linkml-validate -s src/site_kb/schema/site_kb.yaml -C SiteCollection "$f" || exit 1; \
  done

# Validate a single site file
validate-site FILE:
  uv run linkml-validate -s src/site_kb/schema/site_kb.yaml -C SiteCollection {{FILE}}

# Validate ontology term IDs and labels in the schema
prepare-term-sources:
  uv run python -m site_kb.scripts.prepare_term_sources

validate-terms-schema *ARGS: prepare-term-sources
  uv run linkml-term-validator validate-schema src/site_kb/schema/site_kb.yaml -c conf/oak_config.yaml {{ARGS}}

# Validate ontology term IDs and labels in all site data files
validate-terms-data *ARGS: build-db prepare-term-sources
  @for f in db/profiles/*.yaml; do \
    [ -f "$f" ] || continue; \
    uv run linkml-term-validator validate-data "$f" -s src/site_kb/schema/site_kb.yaml -t MeasurementProfileCollection -c conf/oak_config.yaml {{ARGS}} || exit 1; \
  done
  @for f in db/curated/variable_mappings/*.yaml; do \
    [ -f "$f" ] || continue; \
    uv run linkml-term-validator validate-data "$f" -s src/site_kb/schema/site_kb.yaml -t VariableMappingCollection -c conf/oak_config.yaml {{ARGS}} || exit 1; \
  done
  @for f in db/sites/*.yaml; do \
    echo "Validating terms in $f..."; \
    uv run linkml-term-validator validate-data "$f" -s src/site_kb/schema/site_kb.yaml -t SiteCollection -c conf/oak_config.yaml {{ARGS}} || exit 1; \
  done

# Validate both schema and data terms
validate-terms *ARGS:
  just validate-terms-schema {{ARGS}}
  just validate-terms-data {{ARGS}}

# Validate quoted evidence against fetched, reviewed source text
validate-references: build-db
  uv run linkml-reference-validator validate data db/sites/sites.yaml --schema src/site_kb/schema/site_kb.yaml --target-class SiteCollection --config .linkml-reference-validator.yaml --no-full-text

# Fetch a reference for review; --no-cache explicitly refreshes it
fetch-reference REF *ARGS:
  uv run linkml-reference-validator lookup '{{REF}}' --config .linkml-reference-validator.yaml {{ARGS}}

# Fetch sites from DEIMS API and write to db/imported/deims/
fetch-deims *ARGS:
  uv run python -m site_kb.scripts.fetch_deims {{ARGS}}

# Fetch sites from NEON API and write to db/imported/neon/
fetch-neon *ARGS:
  uv run python -m site_kb.scripts.fetch_neon {{ARGS}}

# Fetch from all sources
fetch-all:
  just fetch-deims
  just fetch-neon

# Run all validations
validate-all: validate-db validate-terms validate-references

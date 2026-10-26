"""Apply reviewed crosswalks from verbatim source classifications to site ontology slots."""

from pathlib import Path
import yaml

SLOTS = {"SITE_TYPE": "site_type", "ECOSYSTEM": "ecosystem_terms", "LAND_COVER": "land_cover_terms"}


def read_classification_mappings(directory: Path) -> list[dict]:
    """Load assertions; full LinkML and term validation run separately."""
    mappings = []
    seen = {}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or set(data) != {"mappings"} or not isinstance(data["mappings"], list):
            raise ValueError(f"{path}: expected a mappings list")
        for mapping in data["mappings"]:
            if not isinstance(mapping, dict):
                raise ValueError(f"{path}: mapping must be an object")
            for key in ("source", "scheme", "value"):
                if not isinstance(mapping.get(key), str) or not mapping[key].strip():
                    raise ValueError(f"{path}: mapping requires {key}")
            if mapping.get("target_slot") not in SLOTS:
                raise ValueError(f"{path}: unsupported target_slot")
            target = mapping.get("target")
            if not isinstance(target, dict) or any(not isinstance(target.get(k), str) or not target[k].strip() for k in ("id", "label")):
                raise ValueError(f"{path}: mapping target requires id and label")
            if mapping.get("relation") not in {"EXACT", "CLOSE", "BROAD", "NARROW", "RELATED"}:
                raise ValueError(f"{path}: unsupported mapping relation")
            if mapping.get("origin") not in {"SOURCE", "CURATED"}:
                raise ValueError(f"{path}: unsupported mapping origin")
            evidence = mapping.get("evidence")
            if not isinstance(evidence, list) or not evidence or any(not isinstance(v, str) or not v for v in evidence):
                raise ValueError(f"{path}: mapping requires evidence URLs")
            key = (mapping["source"], mapping["scheme"], mapping["value"], mapping["target_slot"], target["id"])
            if key in seen:
                raise ValueError(f"{path}: duplicate classification mapping {key}")
            seen[key] = path
            mappings.append(mapping)
    return mappings


def apply_classification_mappings(sites: dict[str, dict], mappings: list[dict]) -> None:
    """Add mapped terms with field-level evidence; never replace an existing site_type."""
    by_value = {}
    for mapping in mappings:
        by_value.setdefault((mapping["source"], mapping["scheme"], mapping["value"]), []).append(mapping)
    for identifier, site in sites.items():
        derived_type = None
        for classification in site.get("source_classifications", []):
            key = (classification.get("source"), classification.get("scheme"), classification.get("value"))
            for mapping in by_value.get(key, []):
                slot = SLOTS[mapping["target_slot"]]
                term = {"id": mapping["target"]["id"], "label": mapping["target"]["label"]}
                if slot == "site_type":
                    if derived_type and derived_type != term:
                        raise ValueError(f"{identifier}: conflicting site_type crosswalks {derived_type} and {term}")
                    derived_type = term
                    if site.get("site_type"):
                        continue
                    site["site_type"] = term
                    pointer = "/site_type"
                else:
                    terms = site.setdefault(slot, [])
                    if term not in terms:
                        terms.append(term)
                    pointer = f"/{slot}/{terms.index(term)}"
                site.setdefault("evidence", []).append({
                    "supports": [pointer],
                    "source_url": classification.get("record_url") or mapping["evidence"][0],
                    "source_label": f"{classification['source']} {classification['scheme']}",
                    "locator": f"{classification['scheme']} = {classification['value']}"
                               + (f" ({classification['field_path']})" if classification.get("field_path") else ""),
                    "notes": f"{mapping['origin'].capitalize()} {mapping['relation']} crosswalk to "
                             f"{term['label']} ({term['id']}). " + (mapping.get("notes") or ""),
                })

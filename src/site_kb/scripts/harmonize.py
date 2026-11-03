"""Merge curated same-site clusters and attach checked relations between sites."""

from copy import deepcopy
import math
from pathlib import Path
import re

import yaml

# About 1 km: absorbs coordinate rounding between registries, not real offsets.
GEO_TOLERANCE_DEGREES = 0.01
# Members of one site without a boundary must have points this close together.
MEMBER_DISTANCE_KM = 5.0
SLUG = re.compile(r"site_kb:[a-z0-9]+(-[a-z0-9]+)*")
SINGLE_FIELDS = ("description", "location", "site_type", "status", "established", "closed")
TEXT_FIELDS = ("notes", "variable_notes")
TERM_LISTS = ("ecosystem_terms", "land_cover_terms")
OTHER_LISTS = ("network_registrations", "variables", "datasets", "contacts", "source_classifications")
HANDLED = {"id", "name", "aliases", "evidence", *SINGLE_FIELDS, *TEXT_FIELDS, *TERM_LISTS, *OTHER_LISTS}
SYMMETRIC = {"COLOCATED_WITH", "OVERLAPS"}
INVERSE = {"PART_OF": "HAS_PART"}
COORDINATES = ("latitude", "longitude", "coordinate_datum")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _evidence_ok(item: dict) -> bool:
    evidence = item.get("evidence")
    return isinstance(evidence, list) and bool(evidence) and all(isinstance(v, str) and v for v in evidence)


def read_harmonization(directory: Path) -> tuple[list[dict], list[dict]]:
    """Load clusters and relations; full LinkML validation runs in validate-db."""
    clusters, relations = [], []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        _require(isinstance(data, dict) and set(data) <= {"clusters", "relations"},
                 f"{path}: expected clusters and/or relations lists")
        for cluster in data.get("clusters") or []:
            _require(isinstance(cluster.get("id"), str) and SLUG.fullmatch(cluster["id"]) is not None,
                     f"{path}: cluster id must be a readable site_kb slug")
            _require(isinstance(cluster.get("name"), str) and cluster["name"].strip(), f"{path}: {cluster['id']} needs a name")
            members = cluster.get("members")
            _require(isinstance(members, list) and len(members) >= 2, f"{path}: {cluster['id']} needs at least two members")
            for member in members:
                _require(isinstance(member.get("record"), str) and member.get("origin") in {"SOURCE", "CURATED"}
                         and _evidence_ok(member), f"{path}: {cluster['id']} member needs record, origin and evidence")
            clusters.append(cluster)
        for relation in data.get("relations") or []:
            _require(all(isinstance(relation.get(k), str) for k in ("subject", "object")), f"{path}: relation needs subject and object")
            _require(relation.get("predicate") in {"PART_OF", *SYMMETRIC},
                     f"{path}: curated relations use PART_OF, COLOCATED_WITH or OVERLAPS")
            _require(relation.get("origin") in {"SOURCE", "CURATED"} and _evidence_ok(relation),
                     f"{path}: relation {relation['subject']} {relation['predicate']} needs origin and evidence")
            relations.append(relation)
    return clusters, relations


def _point(site: dict) -> tuple[float, float] | None:
    location = site.get("location") or {}
    if location.get("latitude") is None or location.get("longitude") is None:
        return None
    return location["latitude"], location["longitude"]


def _inside(box: dict, latitude: float, longitude: float) -> bool:
    tolerance = GEO_TOLERANCE_DEGREES
    return (box["west"] - tolerance <= longitude <= box["east"] + tolerance
            and box["south"] - tolerance <= latitude <= box["north"] + tolerance)


def containment(part: dict, whole: dict) -> str:
    """CONSISTENT, VIOLATION, or UNCHECKABLE for a part's point or box inside the whole's box."""
    box = (whole.get("location") or {}).get("bounding_box")
    if not box:
        return "UNCHECKABLE"
    part_box = (part.get("location") or {}).get("bounding_box")
    if part_box:
        corners = [(part_box[y], part_box[x]) for y in ("south", "north") for x in ("west", "east")]
        return "CONSISTENT" if all(_inside(box, *c) for c in corners) else "VIOLATION"
    point = _point(part)
    if point is None:
        return "UNCHECKABLE"
    return "CONSISTENT" if _inside(box, *point) else "VIOLATION"


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = map(math.radians, (a[0], b[0]))
    dlon = math.radians(a[1] - b[1])
    hav = math.sin((lat1 - lat2) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, hav))))


def members_consistent(records: list[dict]) -> bool:
    """Every member point lies in each member box, or all points lie close together."""
    points = [p for p in map(_point, records) if p]
    boxes = [(r.get("location") or {}).get("bounding_box") for r in records]
    boxes = [b for b in boxes if b]
    if boxes:
        return all(_inside(box, *p) for box in boxes for p in points)
    return all(distance_km(a, b) <= MEMBER_DISTANCE_KM for a in points for b in points)


def _append_unique(target: list, value) -> int:
    if value not in target:
        target.append(value)
    return target.index(value)


def merge(cluster: dict, records: list[dict]) -> dict:
    """Combine member records in precedence order, remapping field-level evidence."""
    ids = [r["id"] for r in records]
    for record in records:
        unknown = set(record) - HANDLED
        _require(not unknown, f"{cluster['id']}: no merge rule for {sorted(unknown)} in {record['id']}")
    chosen = {}
    for choice in cluster.get("field_sources") or []:
        _require(choice.get("field") in SINGLE_FIELDS, f"{cluster['id']}: field_sources only covers {SINGLE_FIELDS}")
        _require(choice.get("record") in ids, f"{cluster['id']}: field source {choice.get('record')} is not a member")
        chosen[choice["field"]] = choice["record"]
    site = {"id": cluster["id"], "name": cluster["name"]}
    aliases = []
    for alias in cluster.get("aliases") or []:
        _append_unique(aliases, alias)
    remap = {record["id"]: {} for record in records}
    for record in records:
        if record["name"] != cluster["name"]:
            _append_unique(aliases, record["name"])
        for index, alias in enumerate(record.get("aliases") or []):
            if alias != cluster["name"]:
                remap[record["id"]][f"/aliases/{index}"] = f"/aliases/{_append_unique(aliases, alias)}"
    if aliases:
        site["aliases"] = aliases
    if cluster.get("description"):
        site["description"] = cluster["description"]
    site["members"] = [{"record": m["record"], "name": next(r["name"] for r in records if r["id"] == m["record"]),
                        **{k: m[k] for k in ("origin", "evidence", "notes") if k in m}} for m in cluster["members"]]
    supplier = {}
    for field in SINGLE_FIELDS:
        if field in site:
            continue
        candidates = [r for r in records if r.get(field) is not None]
        if field in chosen:
            candidates = [r for r in records if r["id"] == chosen[field]]
            _require(candidates[0].get(field) is not None, f"{cluster['id']}: {chosen[field]} has no {field}")
        elif field == "site_type":
            distinct = {r["site_type"]["id"] for r in candidates}
            _require(len(distinct) <= 1, f"{cluster['id']}: members disagree on site_type; set field_sources")
        if not candidates:
            continue
        site[field] = deepcopy(candidates[0][field])
        supplier[field] = candidates[0]["id"]
    location_supplier = {}
    if "location" in site:
        location_supplier = {key: supplier["location"] for key in site["location"]}
        for record in records:
            # Coordinates stay together; other location fields may come from any member.
            for key, value in (record.get("location") or {}).items():
                if key not in site["location"] and key not in COORDINATES:
                    site["location"][key] = deepcopy(value)
                    location_supplier[key] = record["id"]
    for field in TEXT_FIELDS:
        texts = [f"{r['id']}: {r[field]}" for r in records if r.get(field)]
        if field == "notes" and cluster.get("notes"):
            texts.insert(0, cluster["notes"])
        if texts:
            site[field] = "\n\n".join(texts)
    for field in TERM_LISTS + OTHER_LISTS:
        merged = []
        for record in records:
            for index, item in enumerate(record.get(field) or []):
                item = deepcopy(item)
                if field == "variables":
                    item.setdefault("source_record", record["id"])
                    merged.append(item)
                    position = len(merged) - 1
                elif field in TERM_LISTS:
                    existing = [t["id"] for t in merged]
                    position = existing.index(item["id"]) if item["id"] in existing else _append_unique(merged, item)
                elif field == "network_registrations":
                    keys = [(r["network"], r["network_id"]) for r in merged]
                    key = (item["network"], item["network_id"])
                    if key in keys:
                        position = keys.index(key)
                        for name, value in item.items():
                            merged[position].setdefault(name, value)
                    else:
                        merged.append(item)
                        position = len(merged) - 1
                else:
                    position = _append_unique(merged, item)
                remap[record["id"]][f"/{field}/{index}"] = f"/{field}/{position}"
        if merged:
            site[field] = merged
    evidence = []
    for record in records:
        for item in record.get("evidence") or []:
            pointers = []
            for pointer in item["supports"]:
                new = _remap_pointer(pointer, record["id"], remap[record["id"]], supplier, location_supplier)
                if new and new not in pointers:
                    pointers.append(new)
            if pointers:
                _append_unique(evidence, {**deepcopy(item), "supports": pointers})
    if evidence:
        site["evidence"] = evidence
    return site


def _remap_pointer(pointer: str, record_id: str, remap: dict, supplier: dict, location_supplier: dict) -> str | None:
    parts = pointer.split("/")
    if len(parts) >= 3 and "/".join(parts[:3]) in remap:
        return remap["/".join(parts[:3])] + ("/" + "/".join(parts[3:]) if len(parts) > 3 else "")
    field = parts[1] if len(parts) > 1 else ""
    if field == "location" and len(parts) > 2:
        return pointer if location_supplier.get(parts[2]) == record_id else None
    if field in SINGLE_FIELDS:
        return pointer if supplier.get(field) == record_id else None
    if field in TEXT_FIELDS:
        return pointer
    return None


def harmonize(records: dict[str, dict], clusters: list[dict], relations: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """Return unified sites keyed by ID and the source records of merged clusters."""
    alias = {}
    for cluster in clusters:
        _require(cluster["id"] not in records, f"{cluster['id']}: cluster ID collides with a record ID")
        for member in cluster["members"]:
            record = member["record"]
            _require(record in records, f"{cluster['id']}: unknown member record {record}")
            _require(record not in alias, f"{record} is a member of both {alias.get(record)} and {cluster['id']}")
            alias[record] = cluster["id"]
    _require(len({c["id"] for c in clusters}) == len(clusters), "Duplicate cluster IDs")
    sites = {identifier: record for identifier, record in records.items() if identifier not in alias}
    source_records = []
    for cluster in clusters:
        members = [records[m["record"]] for m in cluster["members"]]
        if not members_consistent(members) and not cluster.get("geo_check_waiver"):
            raise ValueError(f"{cluster['id']}: member locations disagree; add geo_check_waiver if intended")
        sites[cluster["id"]] = merge(cluster, members)
        source_records.extend(deepcopy(members))
    attach_relations(sites, relations, alias)
    return sites, source_records


def attach_relations(sites: dict[str, dict], relations: list[dict], alias: dict[str, str]) -> None:
    seen = set()
    parents = {}
    for relation in relations:
        subject, obj = (alias.get(relation[k], relation[k]) for k in ("subject", "object"))
        label = f"{relation['subject']} {relation['predicate']} {relation['object']}"
        _require(subject in sites and obj in sites, f"Relation refers to an unknown site: {label}")
        _require(subject != obj, f"Relation links a site to itself: {label}")
        key = (subject, relation["predicate"], obj)
        mirrored = (obj, relation["predicate"], subject) if relation["predicate"] in SYMMETRIC else None
        _require(key not in seen and mirrored not in seen, f"Duplicate relation: {label}")
        seen.add(key)
        assertion = {"predicate": relation["predicate"], "object": obj, "object_name": sites[obj]["name"],
                     "origin": relation["origin"], "evidence": list(relation["evidence"])}
        inverse = {"predicate": INVERSE.get(relation["predicate"], relation["predicate"]), "object": subject,
                   "object_name": sites[subject]["name"], "origin": relation["origin"],
                   "evidence": list(relation["evidence"]), "inferred": True}
        if relation["predicate"] == "PART_OF":
            status = containment(sites[subject], sites[obj])
            if status == "VIOLATION":
                _require(bool(relation.get("geo_check_waiver")), f"{label}: part lies outside the whole's bounding box")
                status = "WAIVED"
            else:
                _require(not relation.get("geo_check_waiver"), f"{label}: geo_check_waiver is stale; the check is {status}")
            assertion["geo_check"] = inverse["geo_check"] = status
            parents.setdefault(subject, []).append(obj)
        for item in (assertion, inverse):
            notes = "; ".join(filter(None, [relation.get("notes"), relation.get("geo_check_waiver")]))
            if notes:
                item["notes"] = notes
        sites[subject].setdefault("relations", []).append(assertion)
        sites[obj].setdefault("relations", []).append(inverse)
    for start in parents:
        stack, visited = list(parents[start]), set()
        while stack:
            node = stack.pop()
            _require(node != start, f"PART_OF cycle through {start}")
            if node not in visited:
                visited.add(node)
                stack.extend(parents.get(node, []))

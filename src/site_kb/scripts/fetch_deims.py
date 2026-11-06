"""Fetch site metadata from the DEIMS-SDR API and write to db/imported/deims/."""

from pathlib import Path
from datetime import datetime, timezone
import json
import math
import re
from urllib.parse import urlsplit

import httpx
import typer
import yaml

from site_kb.scripts.harmonize import outside_own_box_km

DEIMS_API = "https://deims.org/api"
OUTPUT_DIR = Path("db/imported/deims")
RAW_DIR = Path("db/raw/deims")

app = typer.Typer()


def sanitize_filename(name: str) -> str:
    """Convert a site name to a safe filename."""
    safe = name.lower()
    safe = "".join(c if c.isalnum() or c in " -_" else "" for c in safe)
    safe = safe.strip().replace(" ", "_")
    return safe[:80]


def fetch_site_list() -> list[dict]:
    """Fetch the list of all DEIMS sites."""
    resp = httpx.get(f"{DEIMS_API}/sites", timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("DEIMS site list did not return an array (possibly an API error payload)")
    return data


def fetch_site_detail(resource_id: str) -> dict:
    """Fetch detailed metadata for a single DEIMS site."""
    resp = httpx.get(f"{DEIMS_API}/sites/{resource_id}", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or "errors" in data or data.get("type") != "site":
        raise ValueError(f"DEIMS did not return a site record for {resource_id}")
    return data


def _as_text(value: object) -> str | None:
    """Normalize DEIMS scalar/list values to a schema-compatible string."""
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if v is not None and str(v).strip()]
        return ", ".join(parts) if parts else None
    text = str(value).strip()
    return text or None


def _as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _parse_coordinates(value: object) -> tuple[float | None, float | None]:
    """Return latitude and longitude from common DEIMS coordinate shapes."""
    if not value:
        return None, None
    if isinstance(value, str):
        point = re.fullmatch(r"\s*POINT\s*\(\s*([^\s]+)\s+([^\s]+)\s*\)\s*", value, re.IGNORECASE)
        if point:
            return _as_float(point[2]), _as_float(point[1])
        coords = [part.strip() for part in value.split(",")]
        if len(coords) >= 2:
            return _as_float(coords[1]), _as_float(coords[0])
    if isinstance(value, dict):
        lat = _as_float(_first_present(value, "latitude", "lat"))
        lon = _as_float(_first_present(value, "longitude", "lon", "lng"))
        return lat, lon
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return _as_float(value[1]), _as_float(value[0])
    return None, None


def bounding_box(value: object) -> dict | None:
    """West/south/east/north of a WKT (multi)polygon; antimeridian crossings are rejected."""
    if not isinstance(value, str) or not re.match(r"\s*(MULTI)?POLYGON\b", value, re.IGNORECASE):
        return None
    pairs = re.findall(r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s+(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", value)
    points = [(float(x), float(y)) for x, y in pairs]
    if not points or any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in points):
        raise ValueError("DEIMS boundary has no valid longitude/latitude pairs")
    west, east = min(x for x, _ in points), max(x for x, _ in points)
    if east - west > 180:
        raise ValueError("DEIMS boundary appears to cross the antimeridian")
    return {"west": west, "south": min(y for _, y in points), "east": east, "north": max(y for _, y in points)}


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _first_present(values: dict, *keys: str):
    return next((values[key] for key in keys if values.get(key) is not None), None)


def _site_id_from_summary(summary: dict) -> str:
    id_value = summary.get("id")
    if isinstance(id_value, dict):
        return _as_text(id_value.get("suffix") or id_value.get("id")) or ""
    return _as_text(id_value) or ""


def _elevation_from_geographic(geo: dict) -> float | None:
    elevation = geo.get("elevation")
    if isinstance(elevation, dict):
        return _as_float(_first_present(elevation, "avg", "mean", "value"))
    return _as_float(elevation)


ENVIRONMENT_SCHEMES = ("geoBonBiome", "biome", "ecosystemType", "eunisHabitat")


def environment_classifications(env_chars: dict, site_id: str, retrieved_at: str | None) -> list[dict]:
    """Verbatim environmental classes; ENVO terms come only from curated crosswalks."""
    result = []
    for scheme in ENVIRONMENT_SCHEMES:
        values = env_chars.get(scheme)
        pointer = f"/attributes/environmentalCharacteristics/{scheme}"
        entries = list(enumerate(values)) if isinstance(values, list) else [(None, values)]
        for index, value in entries:
            label = value.get("label") if isinstance(value, dict) else value
            if label is None:
                continue
            if not isinstance(label, str):
                raise ValueError(f"DEIMS {site_id}: {scheme} value is not text")
            if label.strip():
                item = {"source": "DEIMS", "scheme": scheme, "value": label.strip(),
                        "record_url": f"{DEIMS_API}/sites/{site_id}",
                        "field_path": pointer if index is None else f"{pointer}/{index}"}
                if retrieved_at:
                    item["retrieved_at"] = retrieved_at
                result.append(item)
    return result


def deims_to_site(summary: dict, detail: dict, retrieved_at: str | None = None) -> dict:
    """Convert DEIMS API response to site-kb Site format."""
    title = _as_text(summary.get("title")) or "Unknown"
    site_id = _site_id_from_summary(summary) or sanitize_filename(title)

    attributes = _as_dict(detail.get("attributes"))
    geo = _as_dict(attributes.get("geographic"))
    # Prefer list coordinates; fall back to the full record (both may be WKT).
    lat, lon = _parse_coordinates(summary.get("coordinates"))
    if lat is None or lon is None:
        lat, lon = _parse_coordinates(geo.get("coordinates"))

    location = {}
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        location["latitude"] = lat
        location["longitude"] = lon

    # Extract country from detail
    country = _as_text(geo.get("country"))
    if location and country:
        location["country"] = country
    elevation = _elevation_from_geographic(geo)
    if location and elevation is not None:
        location["elevation_meters"] = elevation
    box = bounding_box(geo.get("boundaries"))
    box_excluded = None
    if location and box:
        # A boundary that excludes the record's own point is not a usable extent.
        box_excluded = outside_own_box_km({**location, "bounding_box": box})
        if box_excluded is None:
            location["bounding_box"] = box

    site = {
        "id": f"site_kb:deims-{sanitize_filename(title)}",
        "name": title,
        "network_registrations": [
            {
                "network": "DEIMS",
                "network_id": site_id,
                "network_url": f"https://deims.org/{site_id}",
                "name": title,
            }
        ],
    }

    if location:
        site["location"] = location

    # Extract description
    general = _as_dict(attributes.get("general"))
    abstract = _as_text(general.get("abstract"))
    if abstract:
        site["description"] = abstract

    properties = _as_dict(attributes.get("focusDesignScale")).get("observedProperties")
    if properties is not None and not isinstance(properties, list):
        raise ValueError(f"DEIMS {site_id}: observedProperties must be a list or null")
    variables = []
    for index, prop in enumerate(properties or []):
        if not isinstance(prop, dict) or not isinstance(prop.get("label"), str) or not prop["label"].strip():
            raise ValueError(f"DEIMS {site_id}: observedProperties[{index}] has no usable label")
        source = {
            "source": "DEIMS",
            "source_name": prop["label"],
            "record_url": f"{DEIMS_API}/sites/{site_id}",
            "field_path": f"/attributes/focusDesignScale/observedProperties/{index}",
        }
        uri = prop.get("uri")
        if uri is not None and not isinstance(uri, str):
            raise ValueError(f"DEIMS {site_id}: observed property identifier is not a string")
        if uri and uri != "null":
            source["source_id"] = uri
            parsed = urlsplit(uri)
            if parsed.hostname == "vocabs.lter-europe.net" and parsed.path.startswith("/EnvThes/"):
                source["vocabulary"] = "EnvThes"
        if retrieved_at:
            source["retrieved_at"] = retrieved_at
        if detail.get("changed"):
            source["source_modified_at"] = detail["changed"]
        variables.append({
            "name": prop["label"],
            "declaration_kind": "UNSPECIFIED",
            "source_variables": [source],
        })
    if variables:
        site["variables"] = variables

    # Extract ecosystem from environmental characteristics
    env_chars = _as_dict(attributes.get("environmentalCharacteristics"))
    notes = []
    biogeographical_region = _as_text(env_chars.get("biogeographicalRegion"))
    if biogeographical_region:
        notes.append(f"Biogeographical region: {biogeographical_region}")
    if not location:
        if country:
            notes.append(f"DEIMS country: {country}")
        if elevation is not None:
            notes.append(f"DEIMS average elevation: {elevation:g} m")
    if box_excluded is not None:
        notes.append(f"DEIMS boundary omitted: it excludes the record's own coordinates by about "
                     f"{box_excluded:.1f} km; the archived raw record keeps the polygon")
    if notes:
        site["notes"] = "; ".join(notes)
    classifications = environment_classifications(env_chars, site_id, retrieved_at)
    if classifications:
        site["source_classifications"] = classifications

    site["status"] = "ACTIVE"

    return site


def replay(output_dir: Path, raw_dir: Path) -> int:
    """Rebuild each existing record from its archived detail, keeping IDs and filenames."""
    count = 0
    for path in sorted(output_dir.glob("*.yaml")):
        record = yaml.safe_load(path.read_text())["sites"][0]
        identifier = next(r for r in record["network_registrations"] if r["network"] == "DEIMS")["network_id"]
        raw_path = raw_dir / f"{sanitize_filename(identifier)}.json"
        if not raw_path.exists():
            raise ValueError(f"No archived DEIMS record for {identifier}")
        snapshot = json.loads(raw_path.read_text())
        detail_data = snapshot["record"]
        summary = {"id": identifier, "title": detail_data.get("title") or record["name"]}
        site = deims_to_site(summary, detail_data, snapshot["retrieved_at"])
        site["id"] = record["id"]
        path.write_text(yaml.dump({"sites": [site]}, default_flow_style=False, allow_unicode=True, sort_keys=False))
        count += 1
    return count


@app.command()
def main(
    limit: int = typer.Option(0, help="Limit number of sites to fetch (0 = all)"),
    offset: int = typer.Option(0, help="Number of sites to skip before applying limit"),
    output_dir: Path = typer.Option(OUTPUT_DIR, help="Output directory"),
    detail: bool = typer.Option(True, help="Fetch detailed metadata for each site"),
    summary_only: bool = typer.Option(False, help="Print summary statistics only"),
    refresh_existing: bool = typer.Option(False, help="Refresh only records already in output-dir, preserving local IDs and filenames"),
    raw_dir: Path = typer.Option(RAW_DIR, help="Store full source JSON and retrieval provenance here"),
    offline: bool = typer.Option(False, help="Regenerate existing records from archived raw JSON without HTTP"),
):
    """Fetch sites from DEIMS-SDR API."""
    output_dir.mkdir(parents=True, exist_ok=True)
    if offline:
        count = replay(output_dir, raw_dir)
        typer.echo(f"Regenerated {count} site files from {raw_dir}")
        return

    existing = {}
    if refresh_existing:
        sites = []
        for path in sorted(output_dir.glob("*.yaml")):
            record = yaml.safe_load(path.read_text())["sites"][0]
            registration = next(r for r in record["network_registrations"] if r["network"] == "DEIMS")
            identifier = registration["network_id"]
            if identifier in existing:
                raise ValueError(f"Duplicate existing DEIMS identifier: {identifier}")
            existing[identifier] = (path, record["id"])
            sites.append({"id": identifier, "title": record["name"]})
    else:
        typer.echo("Fetching DEIMS site list...")
        sites = fetch_site_list()
    typer.echo(f"Found {len(sites)} sites")

    if offset > 0:
        sites = sites[offset:]
    if limit > 0:
        sites = sites[:limit]

    if summary_only:
        typer.echo(f"Total sites: {len(sites)}")
        return

    for i, summary in enumerate(sites):
        title = _as_text(summary.get("title")) or "Unknown"
        site_id = _site_id_from_summary(summary)
        typer.echo(f"[{i+1}/{len(sites)}] {title}")

        detail_data = {}
        retrieved_at = None
        if detail and site_id:
            detail_data = fetch_site_detail(site_id)
            retrieved_at = datetime.now(timezone.utc).isoformat()
            raw_dir.mkdir(parents=True, exist_ok=True)
            # Store the complete response, not only fields our schema currently uses.
            raw_name = sanitize_filename(site_id)
            (raw_dir / f"{raw_name}.json").write_text(json.dumps({
                "source_url": f"{DEIMS_API}/sites/{site_id}",
                "retrieved_at": retrieved_at,
                "record": detail_data,
            }, indent=2, ensure_ascii=False) + "\n")
            if detail_data.get("title"):
                summary = {**summary, "title": detail_data["title"]}

        site = deims_to_site(summary, detail_data, retrieved_at)
        collection = {"sites": [site]}

        filename = f"deims_{sanitize_filename(title)}.yaml"
        filepath = output_dir / filename
        if site_id in existing:
            filepath, site["id"] = existing[site_id]
        filepath.write_text(yaml.dump(collection, default_flow_style=False, allow_unicode=True, sort_keys=False))

    typer.echo(f"Wrote {len(sites)} site files to {output_dir}")


if __name__ == "__main__":
    app()

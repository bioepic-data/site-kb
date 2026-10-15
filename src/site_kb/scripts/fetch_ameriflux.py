"""Import public AmeriFlux site metadata, with replayable source snapshots."""

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Optional
from urllib.parse import urlsplit

import httpx
import typer
import yaml

from site_kb.scripts.build_db import read_records

API_URL = "https://amfcdn.lbl.gov/api/v1/site_display/AmeriFlux"
SITE_CODE = re.compile(r"[A-Z]{2}-[A-Za-z0-9]{3}")
app = typer.Typer()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def checksum(value: object) -> str:
    """SHA-256 of canonical JSON, not of HTTP transfer bytes."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_records(records: object) -> list[dict]:
    if not isinstance(records, list) or not records:
        raise ValueError("AmeriFlux response must be a nonempty site list, not an API error object")
    identifiers = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("AmeriFlux site record must be an object")
        code = record.get("SITE_ID")
        if not isinstance(code, str) or not SITE_CODE.fullmatch(code):
            raise ValueError(f"Invalid AmeriFlux SITE_ID: {code!r}")
        if code.lower() in identifiers:
            raise ValueError(f"Duplicate or case-colliding AmeriFlux SITE_ID: {code}")
        identifiers.add(code.lower())
        if not isinstance(record.get("SITE_NAME"), str) or not record["SITE_NAME"].strip():
            raise ValueError(f"AmeriFlux {code}: missing SITE_NAME")
    return records


def fetch_snapshot() -> dict:
    response = httpx.get(API_URL, timeout=60, follow_redirects=True)
    response.raise_for_status()
    records = validate_records(response.json())
    return {
        "source_url": API_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "response_sha256": checksum(records),
        "records": records,
    }


def validate_snapshot(snapshot: dict) -> list[dict]:
    if not isinstance(snapshot, dict):
        raise ValueError("Expected an archived AmeriFlux snapshot object")
    records = validate_records(snapshot.get("records"))
    if snapshot.get("source_url") != API_URL:
        raise ValueError("Snapshot has an unexpected source_url")
    try:
        retrieved = datetime.fromisoformat(snapshot["retrieved_at"])
        if retrieved.utcoffset() is None:
            raise ValueError("retrieved_at must have a timezone")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Snapshot requires a timezone-qualified retrieved_at") from exc
    if snapshot.get("response_sha256") != checksum(records):
        raise ValueError("Snapshot checksum mismatch")
    return records


def optional_text(record: dict, key: str) -> str | None:
    value = record.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text or null, got {value!r}")
    return value if value.strip() else None


def number(record: dict, key: str, bounds: tuple[float, float] | None = None) -> float | None:
    value = record.get(key)
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {key}: {value!r}") from exc
    if isinstance(value, bool) or not math.isfinite(result) or result == -9999:
        raise ValueError(f"Invalid {key}: {value!r}")
    if bounds and not bounds[0] <= result <= bounds[1]:
        raise ValueError(f"Out-of-range {key}: {value!r}")
    return result


def ameriflux_to_site(record: dict) -> dict:
    validate_records([record])
    code, name = record["SITE_ID"], record["SITE_NAME"]
    url = optional_text(record, "URL_AMERIFLUX") or f"https://ameriflux.lbl.gov/sites/siteinfo/{code}"
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "ameriflux.lbl.gov":
        raise ValueError(f"AmeriFlux {code}: unexpected site URL {url!r}")
    site = {
        "id": f"site_kb:ameriflux-{code.lower()}",
        "name": name,
        "network_registrations": [{"network": "AMERIFLUX", "network_id": code,
                                   "network_url": url, "name": name}],
    }
    geo = record.get("GRP_LOCATION")
    if geo is None:
        geo = {}
    if not isinstance(geo, dict):
        raise ValueError(f"AmeriFlux {code}: GRP_LOCATION must be an object")
    location = {}
    for source, target, bounds in (("LOCATION_LAT", "latitude", (-90, 90)),
                                   ("LOCATION_LONG", "longitude", (-180, 180)),
                                   ("LOCATION_ELEV", "elevation_meters", None)):
        value = number(geo, source, bounds)
        if value is not None:
            location[target] = value
    country = optional_text(record, "COUNTRY")
    if country:
        location["country"] = "United States" if country == "USA" else country
    state = optional_text(record, "STATE")
    if state:
        location["state_province"] = state
    if location:
        site["location"] = location

    # Preserve source classification and summaries without ontology/measurement claims.
    notes = [f"AmeriFlux site metadata: {url}"]
    for key, label in (("IGBP", "IGBP vegetation code"),
                       ("TOWER_BEGAN", "Reported flux-measurement start year"),
                       ("TOWER_END", "Reported flux-measurement end year")):
        value = optional_text(record, key)
        if value:
            notes.append(f"{label}: {value}")
    climate = record.get("GRP_CLIM_AVG")
    if climate is None:
        climate = {}
    if not isinstance(climate, dict):
        raise ValueError(f"AmeriFlux {code}: GRP_CLIM_AVG must be an object")
    for key, label in (("CLIMATE_KOEPPEN", "Koeppen climate code"),
                       ("MAT", "Source mean annual temperature (degrees C)"),
                       ("MAP", "Source mean annual precipitation (mm)")):
        value = optional_text(climate, key)
        if value:
            notes.append(f"{label}: {value}")
    site["notes"] = "; ".join(notes)
    return site


def existing_records(directory: Path) -> dict[str, tuple[Path, str]]:
    existing = {}
    local_ids = set()
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("sites"), list) or len(data["sites"]) != 1:
            raise ValueError(f"{path}: expected one imported site")
        site = data["sites"][0]
        registrations = [r for r in site.get("network_registrations", []) if r.get("network") == "AMERIFLUX"]
        if len(registrations) != 1 or not isinstance(site.get("id"), str):
            raise ValueError(f"{path}: expected one AmeriFlux registration and a local ID")
        code = registrations[0]["network_id"]
        if not SITE_CODE.fullmatch(code) or code.lower() in existing or site["id"] in local_ids:
            raise ValueError(f"{path}: invalid or duplicate existing identity {code}")
        existing[code.lower()] = (path, site["id"])
        local_ids.add(site["id"])
    return existing


def overlap_candidates(sites: list[dict], comparison_dir: Path) -> list[dict]:
    """Report proximity/name-code evidence; never assert identity or merge sites."""
    candidates = []
    others = read_records(comparison_dir)
    for site in sites:
        for other in others.values():
            if any(r.get("network") == "AMERIFLUX" for r in other.get("network_registrations", [])):
                continue
            reasons = []
            for reg in other.get("network_registrations", []):
                if reg["network"] == "NEON" and "NEON" in site["name"] and re.search(
                    r"\(" + re.escape(reg["network_id"]) + r"\)", site["name"]
                ):
                    reasons.append(f"AmeriFlux name contains NEON code {reg['network_id']}")
            a, b = site.get("location", {}), other.get("location", {})
            if all(v.get(k) is not None for v in (a, b) for k in ("latitude", "longitude")):
                lat1, lat2 = map(math.radians, (a["latitude"], b["latitude"]))
                dlon = math.radians(a["longitude"] - b["longitude"])
                hav = math.sin((lat1 - lat2) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                distance = 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, hav))))
                if distance <= 100:
                    reasons.append(f"Coordinates within 100 m ({distance:.1f} m)")
            if reasons:
                candidates.append({"ameriflux_id": site["network_registrations"][0]["network_id"],
                                   "candidate_site_id": other["id"], "reasons": reasons,
                                   "source_url": site["network_registrations"][0]["network_url"],
                                   "resolution": "UNREVIEWED"})
    return sorted(candidates, key=lambda r: (r["ameriflux_id"], r["candidate_site_id"]))


def ingest(snapshot: dict, output_dir: Path, raw_dir: Path, site_ids: list[str] | None = None,
           limit: int = 0, refresh_existing: bool = False, comparison_dir: Path | None = None,
           summary_only: bool = False) -> dict:
    records = validate_snapshot(snapshot)
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    if output_dir.resolve() == raw_dir.resolve() or output_dir.resolve() in raw_dir.resolve().parents or raw_dir.resolve() in output_dir.resolve().parents:
        raise ValueError("Imported and raw directories must be separate")
    existing = existing_records(output_dir)
    upstream = {r["SITE_ID"]: (i, r) for i, r in enumerate(records)}
    missing = sorted(set(existing) - {code.lower() for code in upstream})
    selected = set(site_ids) if site_ids else set(upstream)
    if selected - upstream.keys():
        raise ValueError(f"Unknown AmeriFlux site IDs: {sorted(selected - upstream.keys())}")
    if refresh_existing:
        selected = {code for code in selected if code.lower() in existing}
    codes = sorted(selected)
    if limit:
        codes = codes[:limit]

    # Map and serialize the entire selected batch before writing any output.
    writes, sites = [], []
    occupied_paths = {path: code for code, (path, _) in existing.items()}
    occupied_ids = {identifier: code for code, (_, identifier) in existing.items()}
    for code in codes:
        index, record = upstream[code]
        site = ameriflux_to_site(record)
        path, site["id"] = existing.get(code.lower(), (output_dir / f"ameriflux_{code.lower()}.yaml", site["id"]))
        if occupied_paths.get(path, code.lower()) != code.lower() or occupied_ids.get(site["id"], code.lower()) != code.lower():
            raise ValueError(f"AmeriFlux {code}: output path or local ID collides with an existing site")
        sites.append(site)
        writes.append((path, yaml.safe_dump({"sites": [site]}, allow_unicode=True, sort_keys=False)))
        raw = {k: snapshot[k] for k in ("source_url", "retrieved_at", "response_sha256")}
        raw.update({"field_path": f"/{index}", "record": record})
        writes.append((raw_dir / f"{code}.json", json.dumps(raw, ensure_ascii=False, indent=2) + "\n"))
    if len({s["id"] for s in sites}) != len(sites):
        raise ValueError("Imported local IDs collide")
    overlaps = overlap_candidates(sites, comparison_dir) if comparison_dir is not None else []
    report = {"source_url": snapshot["source_url"], "retrieved_at": snapshot["retrieved_at"],
              "response_sha256": snapshot["response_sha256"], "available": len(records),
              "selected": codes, "missing_existing_ids": missing,
              "overlap_candidates": overlaps}
    if not summary_only:
        response_path = raw_dir / "responses" / f"{snapshot['response_sha256']}.json"
        # Same content can be fetched on multiple dates; per-site provenance records each retrieval.
        if response_path.exists():
            archived = json.loads(response_path.read_text())
            validate_snapshot(archived)
            if archived["response_sha256"] != snapshot["response_sha256"]:
                raise ValueError(f"Existing response archive is corrupt: {response_path}")
        else:
            atomic_write(response_path, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        for path, content in writes:
            atomic_write(path, content)
        atomic_write(raw_dir / "import-report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


@app.command()
def main(
    site_id: Optional[list[str]] = typer.Option(None, help="Exact case-sensitive site ID; repeat to select multiple sites"),
    limit: int = typer.Option(0, min=0, help="Limit sites after sorting by ID; 0 means all"),
    refresh_existing: bool = typer.Option(False, help="Refresh existing files, preserving IDs and filenames"),
    from_snapshot: Optional[Path] = typer.Option(None, help="Replay an archived responses/*.json file without HTTP"),
    output_dir: Path = typer.Option(Path("db/imported/ameriflux")),
    raw_dir: Path = typer.Option(Path("db/raw/ameriflux")),
    comparison_dir: Path = typer.Option(Path("db/imported"), help="Compare other imports for possible site overlap"),
    summary_only: bool = typer.Option(False, help="Validate and report without writing files"),
):
    """Fetch public site metadata; do not download flux data or assert measurements."""
    snapshot = json.loads(from_snapshot.read_text()) if from_snapshot else fetch_snapshot()
    report = ingest(snapshot, output_dir, raw_dir, site_id, limit, refresh_existing, comparison_dir, summary_only)
    typer.echo(f"Available: {report['available']}; selected: {len(report['selected'])}; overlap candidates: {len(report['overlap_candidates'])}")
    if report["missing_existing_ids"]:
        typer.echo(f"Absent upstream, retained locally: {', '.join(report['missing_existing_ids'])}")
    if not summary_only:
        typer.echo(f"Wrote imports to {output_dir}; provenance and overlap report to {raw_dir}")


if __name__ == "__main__":
    app()

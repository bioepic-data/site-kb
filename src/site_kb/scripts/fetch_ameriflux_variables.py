"""Import site-specific BADM declarations and current published BASE inventories."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import re
import time

import httpx
import typer
import yaml

from site_kb.scripts.fetch_ameriflux import SITE_CODE, atomic_write, checksum, existing_records

SITE_URL = "https://amfcdn.lbl.gov/api/v2/site_info_display/AmeriFlux"
DEFINITIONS_URL = "https://amfcdn.lbl.gov/api/v2/fp_var"
COVERAGE_URL = "https://amfcdn.lbl.gov/api/v2/flux_met_variable_coverage/"
EXCLUDED_TYPES = {"QC_FLAG", "FOOTPRINT", "TIMEKEEPING"}
app = typer.Typer()


def get_snapshot(url: str, client: httpx.Client) -> dict:
    for attempt in range(3):
        try:
            response = client.get(url)
            response.raise_for_status()
            record = response.json()
            return {"source_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": checksum(record), "record": record}
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {429, 500, 502, 503, 504}:
                raise
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def verify_snapshot(snapshot: dict, source_url: str) -> None:
    if snapshot.get("source_url") != source_url or snapshot.get("sha256") != checksum(snapshot.get("record")):
        raise ValueError(f"Invalid source or checksum for {source_url}")
    if datetime.fromisoformat(snapshot["retrieved_at"]).utcoffset() is None:
        raise ValueError("Source retrieval time requires a timezone")


def read_snapshot(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text())


def write_compressed(path: Path, snapshot: dict) -> None:
    """Canonical JSON compressed with a fixed gzip timestamp for stable archives."""
    data = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Cache files are not published inputs until the complete batch is validated.
    path.write_bytes(gzip.compress(data, mtime=0))


def fetch_inputs(cache: Path, refresh: bool = False) -> dict:
    """Resume bounded-concurrency GETs; authentication/download logging is not used."""
    cache.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for filename, url in (("sites.json", SITE_URL), ("definitions.json", DEFINITIONS_URL)):
            path = cache / filename
            if refresh or not path.exists():
                atomic_write(path, json.dumps(get_snapshot(url, client), ensure_ascii=False, indent=2) + "\n")
        sites = read_snapshot(cache / "sites.json")
        verify_snapshot(sites, SITE_URL)
        definitions = read_snapshot(cache / "definitions.json")
        verify_snapshot(definitions, DEFINITIONS_URL)
        values = sites["record"].get("values")
        if not isinstance(values, list) or not values:
            raise ValueError("AmeriFlux v2 site inventory is empty or malformed")
        if any(not isinstance(r, dict) or not isinstance(r.get("site_id"), str) or not SITE_CODE.fullmatch(r["site_id"]) for r in values):
            raise ValueError("Malformed AmeriFlux v2 site identifier")
        definition_index(definitions)
        codes = sorted({r["site_id"] for r in values if r.get("base_variables")})
        failures = {}
        previous_report = cache / "fetch-report.json"
        previous_failures = json.loads(previous_report.read_text()).get("coverage_failures", {}) if previous_report.exists() else {}

        def fetch_one(code):
            path = cache / "coverage" / f"{code}.json.gz"
            if refresh or code in previous_failures or not path.exists():
                write_compressed(path, get_snapshot(COVERAGE_URL + code, client))
            snapshot = read_snapshot(path)
            verify_snapshot(snapshot, COVERAGE_URL + code)
            return code

        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(fetch_one, code): code for code in codes}
            for count, job in enumerate(as_completed(jobs), 1):
                try:
                    job.result()
                except (httpx.HTTPError, ValueError) as exc:
                    failures[jobs[job]] = str(exc)
                if count % 100 == 0 or count == len(codes):
                    typer.echo(f"Coverage checked: {count}/{len(codes)}; failures: {len(failures)}")
        manifest = {"site_sha256": sites["sha256"], "coverage_failures": failures}
        atomic_write(cache / "fetch-report.json", json.dumps(manifest, indent=2) + "\n")
        return manifest


def definition_index(snapshot: dict) -> dict:
    verify_snapshot(snapshot, DEFINITIONS_URL)
    values = snapshot["record"].get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("Empty FP variable definitions")
    result = {}
    for value in values:
        if any(not isinstance(value.get(k), str) or not value[k].strip() for k in ("name", "type", "description", "units")):
            raise ValueError("Malformed FP definition")
        if value["name"] in result:
            raise ValueError(f"Duplicate FP variable {value['name']}")
        result[value["name"]] = value
    return result


def coverage_groups(snapshot: dict, code: str) -> dict:
    verify_snapshot(snapshot, COVERAGE_URL + code)
    data = snapshot["record"]
    if data.get("site_id") != code or data.get("data_product") != "BASE" or not isinstance(data.get("records"), list):
        raise ValueError(f"Invalid BASE coverage response for {code}")
    groups, seen = {}, set()
    for index, row in enumerate(data["records"]):
        if not isinstance(row.get("variable"), str) or not row["variable"] or row.get("resolution") not in {"HH", "HR"}:
            raise ValueError(f"Invalid coverage variable or resolution at {code}/{index}")
        if not isinstance(row.get("version"), str) or not row["version"]:
            raise ValueError(f"Missing coverage version at {code}/{index}")
        qualifiers = row.get("qualifiers")
        if qualifiers is not None and not isinstance(qualifiers, str):
            raise ValueError(f"Invalid qualifiers at {code}/{index}")
        year, percent = row.get("year"), row.get("coverage_percent")
        if type(year) is not int or not 1800 <= year <= 2200 or type(percent) not in (int, float) or not math.isfinite(percent) or not 0 <= percent <= 100:
            raise ValueError(f"Invalid coverage year or percent at {code}/{index}")
        identity = (row["variable"], qualifiers, row["version"], row["resolution"], year)
        if identity in seen:
            raise ValueError(f"Duplicate coverage row at {code}/{index}")
        seen.add(identity)
        if percent <= 0:
            continue
        # PI_F is the FP qualifier for PI-provided gap filling; F is its legacy form.
        gap_filled = bool(re.search(r"(?:^|_)(?:PI_)?F(?:_|$)", qualifiers or ""))
        key = (row["variable"], gap_filled)
        group = groups.setdefault(key, {"years": set(), "versions": set(), "resolutions": set(), "qualifiers": set(), "index": index})
        group["years"].add(year)
        group["versions"].add(row["version"])
        group["resolutions"].add(row["resolution"])
        if qualifiers:
            group["qualifiers"].add(qualifiers)
    return groups


def convert_variables(site_snapshot: dict, definitions: dict, coverage: dict | None) -> tuple[list[dict], str, dict]:
    record = site_snapshot["record"]
    code = record["site_id"]
    variables = []
    counts = {"excluded_diagnostics": 0, "zero_coverage_variables": 0}
    prefix = site_snapshot["field_path"]
    declared, base = record.get("flux_measurements_variables"), record.get("base_variables")
    if not isinstance(declared, list) or not isinstance(base, list) or any(not isinstance(v, str) or not v for v in declared + base):
        raise ValueError(f"Invalid variable lists for {code}")
    for label in dict.fromkeys(declared):
        variables.append({
            "name": f"{label} flux (source-reported)", "declaration_kind": "UNSPECIFIED",
            "data_product": "BADM Site General Information",
            "description": "Flux measurement reported by the site in BADM. The declaration does not specify a BASE column, processing method, or data availability.",
            "evidence": [SITE_URL],
            "source_variables": [{"source": "AMERIFLUX_BADM_SGI", "source_id": label,
                                  "source_name": label, "vocabulary": "BADM flux_measurements_variables",
                                  "record_url": SITE_URL, "field_path": f"{prefix}/flux_measurements_variables/{declared.index(label)}",
                                  "retrieved_at": site_snapshot["retrieved_at"]}],
        })
    groups = coverage_groups(coverage, code) if coverage is not None else None
    bases = list(dict.fromkeys(base))
    # Coverage can include a newly published field before the summary inventory updates.
    if groups is not None:
        bases = sorted(set(bases) | {key[0] for key in groups})
    for basename in bases:
        definition = definitions.get(basename)
        if definition is None:
            raise ValueError(f"Unknown FP variable {basename!r} for {code}; review source definitions")
        category = definition["type"]
        if category in EXCLUDED_TYPES:
            counts["excluded_diagnostics"] += 1
            continue
        variants = [(gap, group) for (name, gap), group in (groups or {}).items() if name == basename]
        if groups is not None and not variants:
            counts["zero_coverage_variables"] += 1
            continue
        if groups is None:
            variants = [(None, None)]
        for gap_filled, group in sorted(variants, key=lambda pair: bool(pair[0])):
            label = f"{definition['description']} ({basename})"
            if gap_filled:
                label += " — gap-filled"
            variable = {
                "name": label, "description": "Derived BASE product." if category == "PRODUCTS" else "Published BASE variable; may be measured or computed.",
                "declaration_kind": "PROPERTY", "data_product": "AmeriFlux BASE", "source_category": category,
                "reported_units": definition["units"], "evidence": [SITE_URL, DEFINITIONS_URL],
            }
            source = {"source": "AMERIFLUX_BASE", "source_id": basename, "source_name": basename,
                      "vocabulary": "AmeriFlux FP", "record_url": SITE_URL,
                      "retrieved_at": site_snapshot["retrieved_at"]}
            if basename in base:
                source["field_path"] = f"{prefix}/base_variables/{base.index(basename)}"
            if group is not None:
                source.update({"record_url": COVERAGE_URL + code, "field_path": f"/records/{group['index']}/variable",
                               "retrieved_at": coverage["retrieved_at"]})
                variable.update({"gap_filled": gap_filled, "available_years": sorted(group["years"]),
                                 "data_versions": sorted(group["versions"]),
                                 "temporal_resolution": ", ".join("half-hourly" if r == "HH" else "hourly" for r in sorted(group["resolutions"]))})
                if group["qualifiers"]:
                    variable["source_qualifiers"] = sorted(group["qualifiers"])
                variable["evidence"].append(COVERAGE_URL + code)
            else:
                variable["description"] += " Coverage details unavailable; gap filling and variable-specific years are unspecified."
            variable["source_variables"] = [source]
            variables.append(variable)
    note = "BADM declarations and published BASE variables are separate evidence types; reported flux species are not concentration variables."
    if not base and not groups:
        note += " No published BASE variable inventory was returned for this site; this does not negate its reported flux measurements."
    elif coverage is None:
        note += " BASE inventory imported; detailed coverage was unavailable."
    else:
        note += " BASE entries require positive reported coverage in at least one year. Years are availability summaries, not continuous monitoring claims."
    note += " Quality flags, footprint diagnostics, and timekeeping columns are excluded from property declarations."
    return variables, note, counts


def load_enrichment(raw_dir: Path, code: str) -> tuple[list[dict], str] | None:
    path = raw_dir / "variables" / f"{code}.json"
    if not path.exists():
        return None
    snapshot = read_snapshot(path)
    verify_snapshot(snapshot, SITE_URL)
    if snapshot["record"].get("site_id") != code:
        raise ValueError(f"Variable snapshot site identity mismatch: {code}")
    root = raw_dir / "variables"
    def archive(kind, digest, suffix):
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid source archive digest")
        return root / kind / f"{digest}{suffix}"
    definitions = read_snapshot(archive("definitions", snapshot["definitions_sha256"], ".json"))
    if definitions["sha256"] != snapshot["definitions_sha256"]:
        raise ValueError("Definition archive identity mismatch")
    coverage = None
    if snapshot.get("coverage_sha256"):
        coverage = read_snapshot(archive("coverage", snapshot["coverage_sha256"], ".json.gz"))
        if coverage["sha256"] != snapshot["coverage_sha256"]:
            raise ValueError("Coverage archive identity mismatch")
    variables, note, _ = convert_variables(snapshot, definition_index(definitions), coverage)
    return variables, note


def import_variables(cache: Path, output_dir: Path, raw_dir: Path) -> dict:
    sites, definitions = (read_snapshot(cache / name) for name in ("sites.json", "definitions.json"))
    verify_snapshot(sites, SITE_URL)
    index = definition_index(definitions)
    existing = existing_records(output_dir)
    fetch_report = json.loads((cache / "fetch-report.json").read_text())
    if fetch_report["site_sha256"] != sites["sha256"]:
        raise ValueError("Fetch report does not match the archived site inventory")
    failures = fetch_report["coverage_failures"]
    report = {"site_source_url": SITE_URL, "site_response_sha256": sites["sha256"],
              "definitions_sha256": definitions["sha256"], "sites": {}, "coverage_failures": failures}
    writes, archives, seen = [], {}, set()
    for i, record in enumerate(sites["record"]["values"]):
        code = record["site_id"]
        if code.lower() in seen:
            raise ValueError(f"Duplicate AmeriFlux variable site: {code}")
        seen.add(code.lower())
        if code.lower() not in existing:
            continue
        snapshot = {"source_url": SITE_URL, "retrieved_at": sites["retrieved_at"], "record": record,
                    "sha256": checksum(record), "field_path": f"/values/{i}",
                    "site_response_sha256": sites["sha256"], "definitions_sha256": definitions["sha256"]}
        coverage = None
        path = cache / "coverage" / f"{code}.json.gz"
        if record["base_variables"] and code not in failures:
            coverage = read_snapshot(path)
            snapshot["coverage_sha256"] = coverage["sha256"]
            archives[coverage["sha256"]] = coverage
        variables, note, counts = convert_variables(snapshot, index, coverage)
        path, _ = existing[code.lower()]
        site = yaml.safe_load(path.read_text())["sites"][0]
        site["variables"] = variables
        site["variable_notes"] = note
        writes.append((path, yaml.safe_dump({"sites": [site]}, allow_unicode=True, sort_keys=False)))
        writes.append((raw_dir / "variables" / f"{code}.json", json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"))
        report["sites"][code] = {"declarations": len(variables), "reported_fluxes": sum(v["data_product"] == "BADM Site General Information" for v in variables),
                                  "base_variables": sum(v["data_product"] == "AmeriFlux BASE" for v in variables),
                                  "gap_filled": sum(v.get("gap_filled") is True for v in variables), **counts}
    if not report["sites"]:
        raise ValueError("No imported AmeriFlux sites match this inventory")
    report["missing_inventory_sites"] = sorted(set(existing) - seen)
    # All responses and transformations are checked before publishing source inputs.
    root = raw_dir / "variables"
    atomic_write(root / "definitions" / f"{definitions['sha256']}.json", json.dumps(definitions, ensure_ascii=False, indent=2) + "\n")
    write_compressed(root / "responses" / f"{sites['sha256']}.json.gz", sites)
    for digest, snapshot in archives.items():
        write_compressed(root / "coverage" / f"{digest}.json.gz", snapshot)
    for path, text in writes:
        atomic_write(path, text)
    atomic_write(root / "import-report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


@app.command()
def main(
    cache: Path = typer.Option(Path(".cache/ameriflux-variables")),
    offline: bool = typer.Option(False, help="Replay cached responses without HTTP"),
    refresh: bool = typer.Option(False, help="Refetch cached source responses"),
    output_dir: Path = typer.Option(Path("db/imported/ameriflux")),
    raw_dir: Path = typer.Option(Path("db/raw/ameriflux")),
):
    """Populate actual site declarations from public v2 metadata and coverage."""
    if offline and refresh:
        raise ValueError("--offline and --refresh cannot be combined")
    if not offline:
        fetch_inputs(cache, refresh)
    report = import_variables(cache, output_dir, raw_dir)
    typer.echo(f"Updated {len(report['sites'])} sites; {sum(s['base_variables'] for s in report['sites'].values())} BASE declarations; {len(report['coverage_failures'])} coverage failures")


if __name__ == "__main__":
    app()

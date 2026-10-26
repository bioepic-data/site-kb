"""Fetch NEON site metadata, classifications, and data products into db/imported/neon/."""

import csv
from datetime import datetime, timezone
import gzip
import io
import json
from pathlib import Path
import re

import httpx
import typer
import yaml

from site_kb.scripts.fetch_ameriflux import atomic_write, checksum

NEON_API = "https://data.neonscience.org/api/v0"
SITES_URL = f"{NEON_API}/sites"
PRODUCTS_URL = f"{NEON_API}/products"
FIELD_SITES_PAGE = "https://www.neonscience.org/field-sites/explore-field-sites"
FIELD_SITES_EXPORT = re.compile(r'href="(/field-sites/exports/NEON_Field_Site_Metadata_\d{8})"')
# Verbatim columns kept as source classifications; ontology terms come from curated crosswalks.
CLASSIFICATION_COLUMNS = ("site_type", "site_subtype", "dominant_nlcd_classes")
OUTPUT_DIR = Path("db/imported/neon")
RAW_DIR = Path("db/raw/neon")
SITE_CODE = re.compile(r"[A-Z]{4}")
PRODUCT_CODE = re.compile(r"DP[0-4]\.\d{5}\.\d{3}")
MONTH = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
VARIABLE_NOTE = (
    "Variables are NEON data products that the NEON API lists with published or "
    "provisional data for this site. A product may bundle several measured, derived, "
    "or quality-control fields, so declarations are not classified as single properties. "
    "Available years are calendar years with at least one available month; they do not "
    "imply continuous collection. Airborne Observation Platform (AOP) products are "
    "remote-sensing surveys over the site, not in-situ measurements."
)

app = typer.Typer()


def fetch_snapshot(url: str, client: httpx.Client) -> dict:
    response = client.get(url)
    response.raise_for_status()
    record = response.json()
    return {"source_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "sha256": checksum(record), "record": record}


def verify_snapshot(snapshot: dict, source_url: str) -> list[dict]:
    if snapshot.get("source_url") != source_url or snapshot.get("sha256") != checksum(snapshot.get("record")):
        raise ValueError(f"Invalid source or checksum for {source_url}")
    if datetime.fromisoformat(snapshot["retrieved_at"]).utcoffset() is None:
        raise ValueError("Source retrieval time requires a timezone")
    data = snapshot["record"].get("data") if isinstance(snapshot["record"], dict) else None
    if not isinstance(data, list) or not data:
        raise ValueError(f"Empty or malformed NEON response from {source_url}")
    return data


def read_snapshot(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def write_snapshot(path: Path, snapshot: dict) -> None:
    """Canonical JSON with a fixed gzip timestamp so unchanged responses are byte-stable."""
    data = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(gzip.compress(data, mtime=0))
    temporary.replace(path)


def field_sites_url(client: httpx.Client) -> str:
    """The dated export link changes with NEON metadata updates, so discover it."""
    response = client.get(FIELD_SITES_PAGE)
    response.raise_for_status()
    links = set(FIELD_SITES_EXPORT.findall(response.text))
    if len(links) != 1:
        raise ValueError(f"Expected one NEON field site metadata export link, found {sorted(links)}")
    return "https://www.neonscience.org" + links.pop()


def fetch_text_snapshot(url: str, client: httpx.Client) -> dict:
    response = client.get(url)
    response.raise_for_status()
    text = response.content.decode("utf-8-sig")
    return {"source_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "sha256": checksum(text), "record": text}


def field_site_rows(snapshot: dict) -> list[dict]:
    if snapshot.get("sha256") != checksum(snapshot.get("record")) or not isinstance(snapshot.get("record"), str):
        raise ValueError("Invalid checksum for NEON field site metadata")
    if datetime.fromisoformat(snapshot["retrieved_at"]).utcoffset() is None:
        raise ValueError("Source retrieval time requires a timezone")
    rows = list(csv.DictReader(io.StringIO(snapshot["record"])))
    if not rows or any(column not in rows[0] for column in ("site_id", *CLASSIFICATION_COLUMNS)):
        raise ValueError("NEON field site metadata lacks expected columns")
    codes = [row["site_id"] for row in rows]
    if any(not SITE_CODE.fullmatch(c) for c in codes) or len(codes) != len(set(codes)):
        raise ValueError("Malformed or duplicate site_id in NEON field site metadata")
    return rows


def classifications(row: dict, row_index: int, snapshot: dict) -> list[dict]:
    """Preserve each value verbatim; NLCD classes are pipe-separated in the export."""
    result = []
    for column in CLASSIFICATION_COLUMNS:
        values = row[column].split("|") if column == "dominant_nlcd_classes" else [row[column]]
        for value in (v.strip() for v in values):
            if value:
                result.append({"source": "NEON", "scheme": column, "value": value,
                               "record_url": snapshot["source_url"], "field_path": f"/{row_index}/{column}",
                               "retrieved_at": snapshot["retrieved_at"]})
    return result


def product_index(snapshot: dict) -> dict[str, dict]:
    result = {}
    for product in verify_snapshot(snapshot, PRODUCTS_URL):
        code = product.get("productCode") if isinstance(product, dict) else None
        if not isinstance(code, str) or not PRODUCT_CODE.fullmatch(code):
            raise ValueError(f"Malformed NEON product code: {code!r}")
        if code in result:
            raise ValueError(f"Duplicate NEON product {code}")
        result[code] = product
    return result


def product_variable(entry: dict, products: dict[str, dict], site_index: int, product_index_: int,
                     retrieved_at: str) -> dict:
    """One declaration per site-listed product; months become years without inferring continuity."""
    code = entry.get("dataProductCode")
    title = entry.get("dataProductTitle")
    if not isinstance(code, str) or not PRODUCT_CODE.fullmatch(code):
        raise ValueError(f"Malformed NEON product code: {code!r}")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"NEON product {code} has no title")
    months = entry.get("availableMonths")
    if not isinstance(months, list) or any(not isinstance(m, str) or not MONTH.fullmatch(m) for m in months):
        raise ValueError(f"Malformed available months for {code}")
    product = products.get(code, {})
    team = product.get("productScienceTeam")
    category = product.get("productCategory")
    description = f"NEON {category or 'data product'}"
    if team:
        description += f" from the {team}"
    description += "; may contain several measured, derived, or quality-control fields."
    variable = {
        "name": title,
        "description": description,
        "declaration_kind": "UNSPECIFIED",
        "data_product": code,
    }
    if category:
        variable["source_category"] = category
    variable["evidence"] = [f"https://data.neonscience.org/data-products/{code}", SITES_URL]
    years = sorted({int(MONTH.fullmatch(m).group(1)) for m in months})
    if years:
        variable["available_years"] = years
    releases = sorted({r["release"] for r in entry.get("availableReleases") or []
                       if isinstance(r, dict) and isinstance(r.get("release"), str) and r.get("availableMonths")})
    if releases:
        variable["data_versions"] = releases
    variable["source_variables"] = [{
        "source": "NEON",
        "source_id": code,
        "source_name": title,
        "vocabulary": "NEON data product catalog",
        "record_url": SITES_URL,
        "field_path": f"/data/{site_index}/dataProducts/{product_index_}",
        "retrieved_at": retrieved_at,
    }]
    return variable


def neon_to_site(neon_site: dict, products: dict[str, dict] | None = None, site_index: int = 0,
                 retrieved_at: str | None = None) -> dict:
    """Convert NEON API site to site-kb Site format."""
    code = neon_site["siteCode"]
    name = neon_site["siteName"]

    site = {
        "id": f"site_kb:neon-{code.lower()}",
        "name": name,
        "location": {
            "latitude": neon_site["siteLatitude"],
            "longitude": neon_site["siteLongitude"],
            "country": "United States",
            "state_province": neon_site.get("stateName"),
        },
        "network_registrations": [
            {
                "network": "NEON",
                "network_id": code,
                "network_url": f"https://www.neonscience.org/field-sites/{code.lower()}",
                "name": name,
                "site_type": neon_site.get("siteType"),
            }
        ],
        "status": "ACTIVE",
    }

    # Add DEIMS cross-reference if available
    deims_id = neon_site.get("deimsId")
    if deims_id:
        # Extract UUID from the DEIMS URL
        deims_uuid = deims_id.rstrip("/").split("/")[-1]
        site["network_registrations"].append(
            {
                "network": "DEIMS",
                "network_id": deims_uuid,
                "network_url": deims_id,
            }
        )

    # Domain info as notes
    domain_code = neon_site.get("domainCode", "")
    domain_name = neon_site.get("domainName", "")
    if domain_code:
        site["notes"] = f"NEON Domain: {domain_code} ({domain_name})"

    if products is not None:
        entries = neon_site.get("dataProducts") or []
        variables = [product_variable(entry, products, site_index, index, retrieved_at)
                     for index, entry in enumerate(entries)]
        codes = [v["data_product"] for v in variables]
        if len(codes) != len(set(codes)):
            raise ValueError(f"Duplicate data products listed for NEON site {code}")
        if variables:
            site["variables"] = sorted(variables, key=lambda v: v["data_product"])
            site["variable_notes"] = VARIABLE_NOTE

    return site


def convert(sites_snapshot: dict, products_snapshot: dict, field_sites_snapshot: dict | None = None) -> list[dict]:
    """Validate the complete batch before any output is written."""
    products = product_index(products_snapshot)
    rows = {}
    if field_sites_snapshot is not None:
        rows = {row["site_id"]: (index, row) for index, row in enumerate(field_site_rows(field_sites_snapshot))}
    records = verify_snapshot(sites_snapshot, SITES_URL)
    codes = [r.get("siteCode") if isinstance(r, dict) else None for r in records]
    if any(not isinstance(c, str) or not SITE_CODE.fullmatch(c) for c in codes):
        raise ValueError("Malformed NEON site code")
    if len(codes) != len(set(codes)):
        raise ValueError("Duplicate NEON site codes")
    sites = [neon_to_site(record, products, index, sites_snapshot["retrieved_at"])
             for index, record in enumerate(records)]
    for site, code in zip(sites, codes):
        if code in rows:
            index, row = rows[code]
            site["source_classifications"] = classifications(row, index, field_sites_snapshot)
    return sites


@app.command()
def main(
    output_dir: Path = typer.Option(OUTPUT_DIR, help="Output directory"),
    raw_dir: Path = typer.Option(RAW_DIR, help="Archive of complete NEON API responses"),
    offline: bool = typer.Option(False, help="Regenerate from archived responses without HTTP"),
    summary_only: bool = typer.Option(False, help="Print summary statistics only"),
):
    """Fetch NEON sites and their data products, archiving both complete responses."""
    sites_path, products_path = raw_dir / "sites.json.gz", raw_dir / "products.json.gz"
    field_sites_path = raw_dir / "field-sites.json.gz"
    if offline:
        sites_snapshot, products_snapshot = read_snapshot(sites_path), read_snapshot(products_path)
        field_sites_snapshot = read_snapshot(field_sites_path) if field_sites_path.exists() else None
    else:
        typer.echo("Fetching NEON sites, data products, and field site metadata...")
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            sites_snapshot = fetch_snapshot(SITES_URL, client)
            products_snapshot = fetch_snapshot(PRODUCTS_URL, client)
            field_sites_snapshot = fetch_text_snapshot(field_sites_url(client), client)
    sites = convert(sites_snapshot, products_snapshot, field_sites_snapshot)
    typer.echo(f"Found {len(sites)} sites with {sum(len(s.get('variables', [])) for s in sites)} site data products")
    unclassified = [s["id"] for s in sites if not s.get("source_classifications")]
    if unclassified:
        typer.echo(f"No field site metadata for: {', '.join(unclassified)}")

    if summary_only:
        for s in sites:
            registration = s["network_registrations"][0]
            typer.echo(f"  {registration['network_id']}: {s['name']} ({registration.get('site_type') or '?'}), "
                       f"{len(s.get('variables', []))} data products")
        return

    if not offline:
        write_snapshot(sites_path, sites_snapshot)
        write_snapshot(products_path, products_snapshot)
        write_snapshot(field_sites_path, field_sites_snapshot)
    output_dir.mkdir(parents=True, exist_ok=True)
    for site in sites:
        filename = f"neon_{site['network_registrations'][0]['network_id'].lower()}.yaml"
        atomic_write(output_dir / filename,
                     yaml.dump({"sites": [site]}, default_flow_style=False, allow_unicode=True, sort_keys=False))

    typer.echo(f"Wrote {len(sites)} site files to {output_dir}")


if __name__ == "__main__":
    app()

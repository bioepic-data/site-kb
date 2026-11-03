"""Propose same-site clusters and site relations from source-asserted links for review."""

import csv
import gzip
import io
import json
from pathlib import Path
import re
import unicodedata

import typer
import yaml

from site_kb.scripts.build_db import read_records
from site_kb.scripts.harmonize import containment, read_harmonization

app = typer.Typer()
NEON_API = "https://data.neonscience.org/api/v0/sites"
AMERIFLUX_NEON_CODE = re.compile(r"\(([A-Z]{4})\)")


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "site_kb:" + re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def registration(record: dict, network: str) -> dict | None:
    return next((r for r in record.get("network_registrations", []) if r["network"] == network), None)


def propose(records: dict[str, dict], field_sites: dict | None) -> dict:
    """Source-asserted NEON↔DEIMS clusters, AmeriFlux NEON tower parts, and NEON colocations."""
    deims = {registration(r, "DEIMS")["network_id"]: r for r in records.values()
             if r["id"].startswith("site_kb:deims-") and registration(r, "DEIMS")}
    neon = {registration(r, "NEON")["network_id"]: r for r in records.values() if r["id"].startswith("site_kb:neon-")}
    clusters, relations = [], []
    for code, record in sorted(neon.items()):
        link = registration(record, "DEIMS")
        if not link or link["network_id"] not in deims:
            continue
        evidence = [f"{NEON_API}/{code}"]
        clusters.append({"id": slugify(record["name"]), "name": record["name"], "members": [
            {"record": record["id"], "origin": "SOURCE", "evidence": evidence},
            {"record": deims[link["network_id"]]["id"], "origin": "SOURCE", "evidence": evidence,
             "notes": "NEON lists this DEIMS ID for the site."}]})
    for record in sorted(records.values(), key=lambda r: r["id"]):
        tower = registration(record, "AMERIFLUX")
        match = AMERIFLUX_NEON_CODE.search(record["name"]) if tower and "NEON" in record["name"] else None
        if not match or match.group(1) not in neon:
            continue
        code = match.group(1)
        whole = deims.get((registration(neon[code], "DEIMS") or {}).get("network_id"), neon[code])
        relations.append({"subject": record["id"], "predicate": "PART_OF", "object": neon[code]["id"], "origin": "CURATED",
                          "evidence": [tower["network_url"], f"https://www.neonscience.org/field-sites/{code.lower()}"],
                          "notes": f"AmeriFlux names this tower for NEON site {code}. "
                                   f"Containment preview: {containment(record, whole)}."})
    if field_sites:
        rows = list(csv.DictReader(io.StringIO(field_sites["record"])))
        pairs = set()
        for row in rows:
            for other in filter(None, (v.strip() for v in row.get("colocated_site", "").split("|"))):
                if row["site_id"] in neon and other in neon:
                    pairs.add(tuple(sorted((row["site_id"], other))))
        for a, b in sorted(pairs):
            relations.append({"subject": neon[a]["id"], "predicate": "COLOCATED_WITH", "object": neon[b]["id"],
                              "origin": "SOURCE", "evidence": [field_sites["source_url"]],
                              "notes": "NEON field site metadata lists these sites as colocated."})
    return {"clusters": clusters, "relations": relations}


def outstanding(proposals: dict, curated: tuple[list[dict], list[dict]]) -> dict:
    """Drop proposals already curated, comparing relations after member-to-cluster resolution."""
    clusters, relations = curated
    alias = {m["record"]: c["id"] for c in clusters for m in c["members"]}
    clustered = set(alias)
    resolve = lambda identifier: alias.get(identifier, identifier)  # noqa: E731
    known = set()
    for r in relations:
        key = (resolve(r["subject"]), r["predicate"], resolve(r["object"]))
        known |= {key, (key[2], key[1], key[0])} if r["predicate"] != "PART_OF" else {key}
    return {"clusters": [c for c in proposals["clusters"] if not any(m["record"] in clustered for m in c["members"])],
            "relations": [r for r in proposals["relations"]
                          if (resolve(r["subject"]), r["predicate"], resolve(r["object"])) not in known]}


@app.command()
def main(
    imported_dir: Path = typer.Option(Path("db/imported")),
    curated_dir: Path = typer.Option(Path("db/curated")),
    field_sites: Path = typer.Option(Path("db/raw/neon/field-sites.json.gz")),
    output: Path = typer.Option(Path("db/staged/harmonization/proposals.yaml")),
):
    """Write uncurated proposals for review; never edits curated harmonization files."""
    records = read_records(imported_dir) | read_records(curated_dir / "sites")
    snapshot = json.loads(gzip.decompress(field_sites.read_bytes())) if field_sites.exists() else None
    result = outstanding(propose(records, snapshot), read_harmonization(curated_dir / "harmonization"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("# Proposals for review; copy accepted entries into db/curated/harmonization/.\n"
                      + yaml.safe_dump(result, sort_keys=False, allow_unicode=True, width=100))
    typer.echo(f"{len(result['clusters'])} cluster and {len(result['relations'])} relation proposals written to {output}")


if __name__ == "__main__":
    app()

"""Assemble imported sites, curated sites, and explicit curated overrides."""

from copy import deepcopy
from pathlib import Path
import os
import tempfile

import typer
import yaml
from site_kb.scripts.variable_catalog import read_catalog, read_profiles, resolve
from site_kb.scripts.variable_mappings import apply_mappings, read_mappings

app = typer.Typer()


def read_records(directory: Path) -> dict[str, dict]:
    """Read SiteCollection-shaped inputs, rejecting ambiguous site identities."""
    records = {}
    origins = {}
    for path in sorted(directory.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or set(data) != {"sites"} or not isinstance(data["sites"], list):
            raise ValueError(f"{path}: expected a mapping containing a sites list")
        for site in data["sites"]:
            if not isinstance(site, dict) or not isinstance(site.get("id"), str) or not site["id"]:
                raise ValueError(f"{path}: each site must have a nonempty string id")
            identifier = site["id"]
            if identifier in records:
                raise ValueError(f"Duplicate site {identifier}: {origins[identifier]} and {path}")
            records[identifier] = site
            origins[identifier] = path
    return records


def apply_override(base: dict, override: dict) -> dict:
    """Merge mappings recursively; replace lists/scalars; null removes a field."""
    result = deepcopy(base)
    for key, value in override.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            previous = result.get(key)
            result[key] = apply_override(previous if isinstance(previous, dict) else {}, value)
        else:
            result[key] = deepcopy(value)
    return result


def validate_site_evidence(site: dict) -> None:
    """Reject evidence attached to absent fields, including stale list indices."""
    for evidence in site.get('evidence', []):
        for pointer in evidence.get('supports', []):
            value = site
            try:
                if not pointer.startswith('/'):
                    raise ValueError('not a JSON Pointer')
                for token in pointer[1:].split('/'):
                    token = token.replace('~1', '/').replace('~0', '~')
                    if isinstance(value, list):
                        if not token.isdecimal() or str(int(token)) != token:
                            raise ValueError('invalid array index')
                        value = value[int(token)]
                    else:
                        value = value[token]
                if value is None:
                    raise ValueError('null field')
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise ValueError(f"{site['id']}: evidence targets absent field {pointer}") from error


def assemble(imported_dir: Path, curated_dir: Path) -> dict:
    sites = read_records(imported_dir)
    curated = read_records(curated_dir / "sites")
    collisions = sites.keys() & curated.keys()
    if collisions:
        raise ValueError(f"Curated sites duplicate imported IDs; use overrides: {sorted(collisions)}")
    sites.update(curated)
    for identifier, override in read_records(curated_dir / "overrides").items():
        if identifier not in sites:
            raise ValueError(f"Override targets unknown site: {identifier}")
        sites[identifier] = apply_override(sites[identifier], override)
    definitions = read_catalog(curated_dir / "variables")
    profiles = read_profiles(curated_dir.parent / "profiles", definitions)
    mappings = read_mappings(curated_dir / "variable_mappings")
    apply_mappings({"catalog": {"variables": list(definitions.values())}}, mappings)
    for site in sites.values():
        if "variables" in site:
            site["variables"] = [resolve(v, definitions) for v in site["variables"]]
    apply_mappings(sites, mappings)
    for identifier, site in sites.items():
        if not site.get("name"):
            raise ValueError(f"Site {identifier} requires a name after applying overrides")
        validate_site_evidence(site)
    if not sites:
        raise ValueError("No sites found; refusing to produce an empty database")
    collection = {"sites": [sites[key] for key in sorted(sites)]}
    if definitions:
        collection["variable_definitions"] = [definitions[key] for key in sorted(definitions)]
    if profiles:
        collection["profiles"] = profiles
    return collection


def build_database(imported_dir: Path, curated_dir: Path, output: Path) -> int:
    """Publish one deterministic collection atomically, without modifying inputs."""
    for source in (imported_dir, curated_dir):
        if output.resolve().is_relative_to(source.resolve()):
            raise ValueError(f"Output must be outside input directory: {source}")
    collection = assemble(imported_dir, curated_dir)
    serialized = yaml.safe_dump(collection, allow_unicode=True, sort_keys=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return len(collection["sites"])


@app.command()
def main(
    imported_dir: Path = typer.Option(Path("db/imported")),
    curated_dir: Path = typer.Option(Path("db/curated")),
    output: Path = typer.Option(Path("db/sites/sites.yaml")),
):
    """Build the database. Run just validate-db to build and validate together."""
    count = build_database(imported_dir, curated_dir, output)
    typer.echo(f"Assembled {count} sites into {output}")


if __name__ == "__main__":
    app()

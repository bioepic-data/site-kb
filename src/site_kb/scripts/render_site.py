"""Render a portable, dependency-free static browser from the assembled database."""
from pathlib import Path
from html import escape
from urllib.parse import urlsplit
import hashlib
import json
import re
import shutil
import typer
import yaml

from site_kb.scripts.bervo_view import build_bervo_view
from site_kb.scripts.build_db import assemble, read_records

app = typer.Typer()
ASSETS = Path(__file__).resolve().parents[1] / 'web'


def esc(value):
    return escape(str(value), quote=True)


def link(url, label):
    parsed = urlsplit(str(url))
    if parsed.scheme not in ('https', 'http') or not parsed.netloc:
        return esc(label)
    return f'<a href="{esc(url)}" rel="noreferrer">{esc(label)} ↗</a>'


def prose(value):
    """Escape source content and make explicit HTTP references clickable."""
    parts, start = [], 0
    for match in re.finditer(r'https?://[^\s<>]+', str(value)):
        url = match.group().rstrip('.,;)')
        parts.extend([esc(str(value)[start:match.start()]), link(url, urlsplit(url).netloc)])
        start = match.start() + len(url)
    parts.append(esc(str(value)[start:]))
    return ''.join(parts)


def slug(identifier):
    readable = re.sub(r'[^a-z0-9]+', '-', identifier.lower()).strip('-')[:90]
    return readable + '-' + hashlib.sha256(identifier.encode()).hexdigest()[:10]


def term(value):
    if not value:
        return '<span class="muted">Not mapped</span>'
    identifier = value['id']
    url = identifier if identifier.startswith(('http://', 'https://')) else None
    if identifier.startswith('MIXS:'):
        url = 'https://w3id.org/mixs/' + identifier.split(':', 1)[1]
    elif identifier.startswith('BERVO:'):
        url = 'https://w3id.org/bervo/BERVO_' + identifier.split(':', 1)[1]
    elif re.fullmatch(r'[A-Za-z]+:\d+', identifier):
        url = 'https://purl.obolibrary.org/obo/' + identifier.replace(':', '_')
    label = f"{value['label']} · {identifier}"
    return link(url, label) if url else esc(label)


def shell(title, body, prefix=''):
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · Site KB</title><meta name="description" content="Explore environmental research sites, measured variables, and their sources.">
<link rel="stylesheet" href="{prefix}assets/style.css"><script defer src="{prefix}assets/app.js"></script></head>
<body><a class="skip" href="#main">Skip to content</a><header class="topbar"><a class="brand" href="{prefix}index.html"><span class="brandmark" aria-hidden="true">◎</span> site<span class="brand-light">kb</span></a><span class="top-label">ENVIRONMENTAL RESEARCH REGISTRY</span><nav aria-label="Main"><a href="{prefix}index.html">Explore sites</a><a href="{prefix}variables.html">Variables & profiles</a><a href="{prefix}data/sites.json" download>Download data ↓</a></nav></header>
{body}<footer><span>Site KB <span class="muted">/ Environmental research, connected.</span></span><span>Source-linked records · Open static catalog</span></footer></body></html>'''


def badge(text, kind=''):
    return f'<span class="badge {kind}">{esc(text)}</span>'


def networks(site):
    return sorted({r['network'] for r in site.get('network_registrations', [])})


def country(site):
    return site.get('location', {}).get('country') or 'Not recorded'


def card(site, origin):
    nets = networks(site)
    variables = site.get('variables', [])
    search = json.dumps(site, ensure_ascii=False).lower()
    return f'''<article class="site-card" data-search="{esc(search)}" data-networks="{esc(json.dumps(nets))}" data-country="{esc(country(site))}" data-origin="{origin}" data-variables="{bool(variables).__str__().lower()}">
<div class="card-top">{''.join(badge(n) for n in nets) or badge('Independent')} {badge(origin, 'origin')}</div>
<h2><a href="sites/{slug(site['id'])}.html">{esc(site['name'])}<span aria-hidden="true">↗</span></a></h2>
<p class="location">{esc(' · '.join(filter(None, [site.get('location', {}).get('state_province'), country(site)])))}</p>
{('<p>' + badge(site['site_type']['label']) + '</p>') if site.get('site_type') else ''}
<p class="card-description">{esc(site.get('description') or 'Explore network registrations and available site metadata.')}</p>
<div class="card-bottom"><span>{len(variables)} property declarations</span><span>{esc(site.get('status', 'Unknown').capitalize())}</span></div></article>'''


def select(name, label, values):
    return f'<label for="{name}">{label}</label><select id="{name}"><option value="">All {label.lower()}</option>' + ''.join(f'<option>{esc(v)}</option>' for v in values) + '</select>'


def variable_provenance(variable):
    kinds = {"PROPERTY": "Specific property", "PARAMETER_GROUP": "Parameter group", "UNSPECIFIED": "Source declaration · granularity unclassified"}
    result = badge(kinds.get(variable.get('declaration_kind'), 'Granularity not recorded'), 'neutral')
    for source in variable.get('source_variables', []):
        identifier = source.get('source_id')
        fields = f'<dt>Source</dt><dd>{esc(source["source"])} · {esc(source.get("vocabulary", ""))}</dd><dt>Source name</dt><dd>{esc(source["source_name"])}</dd>'
        if identifier:
            fields += f'<dt>Source ID</dt><dd>{link(identifier, identifier)}</dd>'
        if source.get('record_url'):
            fields += f'<dt>Source record</dt><dd>{link(source["record_url"], "Original JSON")}</dd>'
        for key, label in [('field_path', 'Source field'), ('retrieved_at', 'Retrieved'), ('source_modified_at', 'Source modified')]:
            if source.get(key):
                fields += f'<dt>{label}</dt><dd>{esc(source[key])}</dd>'
        result += f'<dl>{fields}</dl>'
    for mapping in variable.get('mappings', []):
        result += f'<div class="mapping"><strong>{esc(mapping["origin"].capitalize())} crosswalk</strong><p>{link(mapping["source_id"], mapping.get("source_name", mapping["source_id"]))} → {esc(mapping["relation"])} → {term(mapping["target"])}</p><p>Evidence: ' + ' · '.join(link(url, urlsplit(url).netloc) for url in mapping['evidence']) + '</p>'
        if mapping.get('attributed_to'):
            result += f'<p>Attributed to {esc(mapping["attributed_to"])}</p>'
        if mapping.get('asserted_on'):
            result += f'<p>Asserted on {esc(mapping["asserted_on"])}</p>'
        if mapping.get('notes'):
            result += f'<p>{prose(mapping["notes"])}</p>'
        result += '</div>'
    if not variable.get('mappings'):
        result += '<p class="muted mapping-note">No crosswalk assertions recorded.</p>'
    return result


def evidence_refs(site, pointer):
    refs = [f'<a class="evidence-ref" href="#evidence-{i}" aria-label="Evidence {i}">[{i}]</a>'
            for i, item in enumerate(site.get('evidence', []), 1) if pointer in item['supports']]
    return ' ' + ' '.join(refs) if refs else ''


def evidence_panel(site):
    items = []
    for i, item in enumerate(site.get('evidence', []), 1):
        labels = []
        for pointer in item['supports']:
            label = pointer.strip('/').replace('location/', '').replace('network_registrations/0', 'network registration').replace('_', ' ').replace('/', ' · ').capitalize()
            labels.append(label)
        quote = f'<blockquote>{esc(item["quotation"])}</blockquote>' if item.get('quotation') else ''
        accessed = f' · Checked {esc(item["accessed_on"])}' if item.get('accessed_on') else ''
        notes = f'<p>{prose(item["notes"])}</p>' if item.get('notes') else ''
        items.append(f'<article class="source-evidence" id="evidence-{i}"><h3>[{i}] {link(item["source_url"], item["title"])}</h3><p class="evidence-supports">Supports: {esc(", ".join(labels))}</p><p class="muted">{esc(item["locator"])}{accessed}</p>{quote}{notes}</article>')
    return '<section class="panel"><h2>Evidence for this record</h2>' + ''.join(items) + '</section>' if items else ''


def detail(site, origin, input_paths):
    prefix = '../'
    variables = site.get('variables', [])
    rows = []
    for variable in variables:
        extra = ''.join(f'<dt>{label}</dt><dd>{term(variable[key])}</dd>' for key, label in [('term', 'Canonical term'), ('units', 'Units'), ('capability', 'Capability')] if variable.get(key))
        extra += ''.join(f'<dt>{label}</dt><dd>{esc(variable[key])}</dd>' for key, label in [('temporal_resolution', 'Sampling interval'), ('network_variable_id', 'Source variable ID')] if variable.get(key))
        for key, label in [('method', 'Method'), ('sample_context', 'Sample context'), ('sampling_period', 'Study sampling period'), ('reported_units', 'Reported units')]:
            if variable.get(key):
                extra += f'<dt>{label}</dt><dd>{esc(variable[key])}</dd>'
        if variable.get('variable_id'):
            extra += f'<dt>Shared definition</dt><dd><a href="../variables.html#{slug(variable["variable_id"])}">{esc(variable["variable_id"])}</a></dd>'
        if variable.get('evidence'):
            extra += '<dt>Site evidence</dt><dd>' + '<br>'.join(link(url, url) for url in variable['evidence']) + '</dd>'
        if variable.get('additional_terms'):
            extra += '<dt>Additional terms</dt><dd>' + '<br>'.join(term(t) for t in variable['additional_terms']) + '</dd>'
        rows.append(f'<article class="variable"><h3>{esc(variable["name"])}</h3><p>{prose(variable.get("description", ""))}</p>{variable_provenance(variable)}{"<dl>" + extra + "</dl>" if extra else ""}</article>')
    var_html = ''.join(rows) or '<div class="empty-inline">No observed properties documented yet.<p>This is a metadata gap; it does not mean the site has no measurements.</p></div>'
    loc = site.get('location', {})
    facts = [('Country', country(site), '/location/country'), ('Region', loc.get('state_province'), '/location/state_province'), ('Latitude', loc.get('latitude'), '/location/latitude'), ('Longitude', loc.get('longitude'), '/location/longitude'), ('Elevation (m)', loc.get('elevation_meters'), '/location/elevation_meters'), ('Established', site.get('established'), '/established'), ('Closed', site.get('closed'), '/closed')]
    facts_html = ''.join(f'<dt>{label}</dt><dd>{esc(value)}{evidence_refs(site, pointer)}</dd>' for label, value, pointer in facts if value is not None)
    has_coordinates = loc.get('latitude') is not None and loc.get('longitude') is not None
    coordinate_note = '<p class="muted coordinate-note">Coordinates not recorded.</p>'
    if has_coordinates:
        coordinate_note = f'<p class="muted coordinate-note">Coordinate datum: {esc(loc.get("coordinate_datum") or "not reported")}. '
        if not all(evidence_refs(site, '/location/' + key) for key in ('latitude', 'longitude')):
            coordinate_note += 'Field-specific coordinate evidence not recorded. '
        coordinate_note += '</p>'
    registrations = ''.join(f'<article class="registration"><strong>{esc(r["network"])}</strong><p>{link(r.get("network_url", ""), r["network_id"])}</p><span class="muted">{esc(r.get("site_type", ""))}</span></article>' for r in site.get('network_registrations', [])) or '<p class="muted">No network registrations recorded.</p>'
    contacts = ''.join(f'<p><strong>{esc(c["name"])}</strong><br>{esc(c.get("role", ""))}<br><span class="muted">{esc(c.get("organization", ""))}</span></p>' for c in site.get('contacts', [])) or '<p class="muted">No contacts recorded.</p>'
    source_links = ''.join(f'<li><a href="../sources/{esc(p)}">{esc(p)}</a></li>' for p in input_paths)
    classification = '<section class="panel"><h2>Site type</h2>' + term(site['site_type']) + '<p class="muted">Physical facility or site classification, separate from ecosystem annotations.</p></section>' if site.get('site_type') else ''
    datasets = ''.join(f'<article class="variable"><h3>{link(d["url"], d["title"])}</h3><p>{esc(d["assay"])} · {esc(d["availability"])}</p><p>{esc(d.get("accession", ""))}</p><p>{prose(d.get("notes", ""))}</p></article>' for d in site.get('datasets', []))
    dataset_html = f'<section class="panel"><h2>Associated datasets</h2>{datasets}</section>' if datasets else ''
    raw = esc(yaml.safe_dump({'sites': [site]}, sort_keys=False, allow_unicode=True))
    body = f'''<main id="main" class="detail-main"><a class="back" href="../index.html">← All sites</a>
<div class="detail-heading"><div class="eyebrow">SITE RECORD / {esc(origin.upper())}</div><h1>{esc(site['name'])}</h1><div class="tags">{badge(site.get('status', 'Unknown').capitalize(), 'status')}{''.join(badge(n) for n in networks(site))}</div><p class="intro">{prose(site.get('description', ''))}</p><p class="muted aliases">{esc('Also known as: ' + '; '.join(site['aliases'])) if site.get('aliases') else ''}</p></div>
<div class="detail-grid"><div>{evidence_panel(site)}{dataset_html}<section class="panel"><div class="section-title"><h2>Observed properties & variables</h2>{badge(str(len(variables)))}</div><p class="muted">Declarations may include broad parameter groups. Source vocabulary identities and ontology crosswalks are shown separately.</p>{var_html}</section>
<section class="panel"><h2>Notes & evidence</h2><p class="evidence">{prose(site.get('notes', 'No additional notes recorded.'))}</p></section>
<section class="panel"><h2>Provenance</h2><p>Record origin: <strong>{esc(origin)}</strong>. Source files used to assemble this record:</p><ul class="source-list">{source_links}</ul><details><summary>View assembled YAML</summary><pre>{raw}</pre></details></section></div>
<aside>{classification}<section class="panel"><h2>Location & dates</h2><dl>{facts_html}</dl>{coordinate_note}</section><section class="panel"><h2>Network registrations</h2>{registrations}</section><section class="panel"><h2>Contacts</h2>{contacts}</section><section class="panel"><h2>Ecosystems</h2>{'<br>'.join(term(t) for t in site.get('ecosystem_terms', [])) or '<p class="muted">Not annotated.</p>'}</section></aside></div></main>'''
    return shell(site['name'], body, prefix)



def catalog_page(collection):
    definitions = {v['id']: v for v in collection.get('variable_definitions', [])}
    bervo = build_bervo_view(collection)
    groups = []
    for group in bervo['groups']:
        definitions_html = ''.join(f'<li><a href="#{slug(v["id"])}">{esc(v["name"])}</a> · {esc(v["relation"])}</li>' for v in group['definitions'])
        sites_html = ''.join(f'<li><a href="sites/{slug(v["site_id"])}.html">{esc(v["site_name"])}</a> — {esc(v["variable_name"])} · {esc(v["relation"])}</li>' for v in group['site_declarations'])
        groups.append(f'<section class="panel"><h3>{term(group["term"])}</h3><ul>{definitions_html}</ul><details><summary>{len(group["site_declarations"])} site declarations</summary><ul>{sites_html}</ul></details></section>')
    summary = bervo['summary']
    unmapped = ''.join(f'<li><a href="#{slug(v["id"])}">{esc(v["name"])}</a></li>' for v in bervo['unmapped_catalog_definitions'])
    bervo_html = f'<h2>Browse by BERVO</h2><p>{summary["mapped_catalog_definition_count"]} of {summary["catalog_definition_count"]} shared definitions and {summary["mapped_site_declaration_count"]} of {summary["site_declaration_count"]} site declarations have BERVO annotations. <a href="data/bervo.json">Download BERVO index</a></p><p>EXACT indicates equivalent properties; CLOSE indicates similar scope; BROAD means the BERVO target is more general. Sharing a broader term does not make measurements interchangeable.</p>' + ''.join(groups) + f'<details class="panel"><summary>{len(bervo["unmapped_catalog_definitions"])} shared definitions without BERVO mappings</summary><ul>{unmapped}</ul></details>'
    profiles = []
    for profile in collection.get('profiles', []):
        candidates = []
        for candidate in profile.get('candidates', []):
            variable = definitions[candidate['variable_id']]
            details = ' · '.join(f'{key.removeprefix("source_")}: {candidate[key]}' for key in ('source_range', 'source_required', 'source_multivalued', 'source_preferred_unit') if key in candidate)
            candidates.append(f'<li><a href="#{slug(variable["id"])}">{esc(variable["name"])}</a> — {esc(candidate["category"])}<br><small>{esc(details)}</small></li>')
        profiles.append(f'<section class="panel"><h2>{esc(profile["name"])}</h2><p>{term(profile.get("extension"))}</p><p>Applies to: {term(profile.get("applies_to"))} ({esc(profile.get("applicability_scope", "unspecified scope"))})</p><p>{link(profile["source_url"], profile["source_version"])}</p><p>{prose(profile.get("notes", ""))}</p><ul>{"".join(candidates)}</ul></section>')
    entries = []
    for identifier, variable in sorted(definitions.items(), key=lambda item: item[1]['name'].casefold()):
        site_links = ''.join(f'<li><a href="sites/{slug(site["id"])}.html">{esc(site["name"])}</a></li>' for site in collection['sites'] if any(v.get('variable_id') == identifier for v in site.get('variables', [])))
        entries.append(f'<article class="panel" id="{slug(identifier)}"><h2>{esc(variable["name"])}</h2><p class="muted">{esc(identifier)}</p><p>{prose(variable.get("description", ""))}</p><p>{term(variable.get("term"))}</p>{variable_provenance(variable)}<h3>Documented at sites</h3><ul>{site_links}</ul>{"" if site_links else "<p>No site declarations reference this definition yet.</p>"}</article>')
    body = '<main id="main" class="detail-main"><div class="page-heading"><div><h1>Variables & environment profiles</h1><p>Shared definitions preserve source identities and reviewed mappings. Profiles describe possible fields; only explicit site declarations establish collection.</p></div></div><h2>Candidate profiles</h2>' + ''.join(profiles) + bervo_html + '<h2>Shared variable definitions</h2>' + ''.join(entries) + '</main>'
    return shell('Variables and profiles', body)


def render(output=Path('site'), imported=Path('db/imported'), curated=Path('db/curated')):
    collection = assemble(imported, curated)
    sites = sorted(collection['sites'], key=lambda s: (s['name'].casefold(), s['id']))
    curated_ids = read_records(curated / 'sites')
    override_ids = read_records(curated / 'overrides')
    origins = {s['id']: ('Curated' if s['id'] in curated_ids else 'Enriched' if s['id'] in override_ids or any(m.get('origin') == 'CURATED' for v in s.get('variables', []) for m in v.get('mappings', [])) else 'Imported') for s in sites}
    # The output is a dedicated generated directory, never an input or repository root.
    resolved = output.resolve()
    if resolved == Path.cwd().resolve() or any(source.resolve().is_relative_to(resolved) or resolved.is_relative_to(source.resolve()) for source in (imported, curated, ASSETS)):
        raise ValueError('Output must be a dedicated directory outside the inputs')
    if output.exists():
        if not (output / '.site-kb-generated').exists():
            raise ValueError(f'Refusing to replace an unrecognized output directory: {output}')
        shutil.rmtree(output)
    for folder in ('assets', 'sites', 'data', 'sources'):
        (output / folder).mkdir(parents=True, exist_ok=True)
    (output / '.site-kb-generated').touch()
    (output / '.nojekyll').touch()
    for asset in ASSETS.iterdir():
        shutil.copyfile(asset, output / 'assets' / asset.name)
    paths = {s['id']: [] for s in sites}
    for root, label in ((imported, 'imported'), (curated, 'curated')):
        for path in sorted(root.rglob('*.yaml')):
            relative = Path(label) / path.relative_to(root)
            dest = output / 'sources' / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            data = yaml.safe_load(path.read_text())
            if 'sites' in data:
                for record in data['sites']:
                    paths[record['id']].append(relative.as_posix())
            elif 'variable_definitions' in data:
                identifiers = {v['id'] for v in data['variable_definitions']}
                for site in sites:
                    if any(v.get('variable_id') in identifiers for v in site.get('variables', [])):
                        paths[site['id']].append(relative.as_posix())
            elif 'mappings' in data:
                for site in sites:
                    if any(m in data['mappings'] for v in site.get('variables', []) for m in v.get('mappings', [])):
                        paths[site['id']].append(relative.as_posix())
    raw_dir = imported.parent / 'raw' / 'deims'
    for raw_path in sorted(raw_dir.glob('*.json')):
        snapshot = json.loads(raw_path.read_text())
        identifier = snapshot['record']['id']['suffix']
        matching = [s for s in sites if any(r['network'] == 'DEIMS' and r['network_id'] == identifier for r in s.get('network_registrations', []))]
        if not matching:
            continue
        relative = Path('raw/deims') / raw_path.name
        destination = output / 'sources' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw_path, destination)
        for site in matching:
            paths[site['id']].append(relative.as_posix())
    for path in sorted((curated.parent / 'profiles').glob('*.yaml')):
        destination = output / 'sources' / 'profiles' / path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    (output / 'variables.html').write_text(catalog_page(collection))
    (output / 'data/bervo.json').write_text(json.dumps(build_bervo_view(collection), ensure_ascii=False, indent=2))
    (output / 'data/sites.json').write_text(json.dumps(collection, ensure_ascii=False, indent=2, default=str))
    for site in sites:
        (output / 'sites' / (slug(site['id']) + '.html')).write_text(detail(site, origins[site['id']], paths[site['id']]))
    countries = sorted({country(s) for s in sites})
    nets = sorted({n for s in sites for n in networks(s)})
    variable_sites = sum(bool(s.get('variables')) for s in sites)
    cards = ''.join(card(s, origins[s['id']]) for s in sites)
    filters = select('network', 'Networks', nets) + select('country', 'Countries', countries) + select('origin', 'Record origins', sorted(set(origins.values())))
    body = f'''<main id="main" class="explorer"><div class="page-heading"><div><div class="eyebrow">THE SITE DIRECTORY</div><h1>Explore the field.</h1><p>Research sites, measured variables, and the evidence behind them.</p></div><div class="collection-label"><span class="live-dot"></span> {len(sites)} records in this collection</div></div>
<div class="stats"><div><strong>{len(sites)}</strong><span>Site records</span></div><div><strong>{len(nets)}</strong><span>Networks represented</span></div><div><strong>{sum(c != 'Not recorded' for c in countries)}</strong><span>Countries recorded</span></div><div><strong>{variable_sites}</strong><span>Sites with property metadata</span></div></div>
<div class="workspace"><aside class="filters"><form id="filters"><h2>Refine collection</h2>{filters}<label class="check"><input type="checkbox" id="variables"> With observed properties</label><button type="reset" class="reset">Reset filters ↺</button></form><div class="coverage-note"><strong>A growing knowledge base</strong><p>Missing metadata means not yet documented. Network memberships may overlap.</p></div></aside>
<section class="results" aria-label="Site results"><label class="search-label" for="search">Search the collection</label><input type="search" id="search" placeholder="Search sites, places, variables, or ontology IDs…" autocomplete="off"><div class="results-heading"><p id="result-count" role="status" aria-live="polite">{len(sites)} sites</p><span>Name A–Z</span></div><noscript><p>Search and filters need JavaScript. All site records remain available below.</p></noscript><div id="cards" class="cards">{cards}</div><div id="empty" class="empty-inline" hidden><h2>No matching sites</h2><p>Try a broader search or reset your filters.</p><button id="clear-search">Clear search & filters</button></div></section></div></main>'''
    (output / 'index.html').write_text(shell('Explore environmental sites', body))
    return len(sites)


@app.command()
def main(output: Path = typer.Option(Path('site'))):
    typer.echo(f'Rendered {render(output)} site pages into {output}')


if __name__ == '__main__':
    app()

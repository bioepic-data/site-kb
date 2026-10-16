# NGEE site curation

Reviewed 2026-10-15. This import covers both Next-Generation Ecosystem
Experiments projects. It adds 18 independently curated records and two network
enum values. Source evidence is carried in each record's registration, field-specific evidence, and notes.

## Sources and coverage

- [NGEE Arctic location index evidence](https://ngee-arctic.ornl.gov/highlights/remote-sensing-from-unoccupied-aerial-systems-opportunities-to-enhance-arctic-plant)
  links seven specific project locations: Utqiagvik (Barrow), Kougarok mile
  markers 64, 80, and 86, Teller mile markers 27 and 47, and Council mile marker
  71. Each linked location page was checked individually. Alaska and Seward
  Peninsula tags are regional containers and are not added as sites.
- [NGEE Arctic summary](https://ngee-arctic.ornl.gov/summary) supplies the BEO
  context for the Utqiagvik field location.
- [NGEE Tropics field overview](https://ngee-tropics.lbl.gov/research/field/)
  names eleven sites: Sabana, El Verde, Icacos, Barro Colorado Island, Parque
  Natural Metropolitano, San Lorenzo, Agua Salud, ZF2, Lambir Hills, Daintree
  Research Observatory, and Paracou. The page describes Phase 2; it is not a
  current operational-status registry. Its ten unspecified ForestGEO partner
  sites cannot be resolved into additional site records from that page alone.
- [NGEE Tropics Phase 2 proposal](https://ngee-tropics.lbl.gov/wp-content/uploads/sites/16/2020/01/NGEE-TROPICS-Phase-2-Proposal_Final_distributable.pdf),
  printed page 46, supplies coordinates for BCI (9.154, -79.848; 150 m), PNM
  (8.99441, -79.543), and San Lorenzo (9.280996, -79.978162; 120 m), as well as
  the Fort Sherman alias. These are source-reported site points, not boundaries. Printed p. 47 (PDF
  p. 55) supplies a park reference point for Lambir Hills; printed p. 48 (PDF
  p. 56) supplies the Paracou station point. Their degree-minute notation is
  retained in short quotations and converted explicitly to decimal degrees.

The source Arctic location URI serves as `network_id`. Tropics has no formal
codes in its overview, so its source site names serve as identifiers, explicitly
documented in each record. Local `site_kb` identifiers are curation keys, not
purported upstream codes. The records preserve upstream registration names.

## Field-level provenance

Every NGEE record now has structured evidence and a site description. Five
coordinate-bearing records attach evidence directly to latitude, longitude, and
any reported elevation. PDF links open at the physical PDF page, while locators
also name the printed page and site paragraph. Brief quotations preserve source
notation; interpretation notes distinguish park/island/station/crane reference
points, explain conversions and precision, and disclose that the cited passages
do not specify a geodetic datum. WGS84 is no longer assumed by the schema.

ZF2 provides a range, so its location remains without an invented point. The
Agua Salud coordinate notation in the PDF is ambiguous and remains unresolved.
Both limitations have source-specific evidence. The source PDF was downloaded
and relevant coordinate pages visually checked; the local scratch copy is under
Git-ignored `cache/ngee/`, not a new tracked upstream snapshot.

Teller-27 and Kougarok-64 descriptions also use
[Conroy et al. (2023), section 2.1](https://tc.copernicus.org/articles/17/3987/2023/#section2),
which distinguishes the catchment and hillslope settings. This contextual
addition does not assert new measurement declarations.

## Identity and spatial scope

Mile-marker sites remain distinct: Kougarok 64, 80, and 86 are not aliases of
one location. Road or town coordinates must not be substituted for plot points.

Existing DEIMS records were searched for names and aliases. Three overlaps need
care because the source footprints differ:

| NGEE record | Existing record | Treatment |
| --- | --- | --- |
| Utqiagvik (Barrow) | BARC/BEO, `deims:6b3b8511-2669-4170-8487-17e135578dad` | NGEE field-location scope overlaps the broader facility/observatory record; exact equivalence unresolved. |
| El Verde | Luquillo Forest Dynamics Plot, `deims:d71bb3ec-11b7-49da-a246-d15120505c8d`, and Luquillo LTER | A locality, a particular plot, and a regional research program are not automatically identical. |
| Daintree Research Observatory | Daintree SuperSite, `deims:01d7ab82-94cd-4b53-9dc3-a409c4498895` | DEIMS explicitly includes both the observatory and the Discovery Centre; retain the narrower NGEE site separately. |

No registrations, measurements, coordinates, or aliases are copied across these
overlaps. Site counts therefore count source-scoped records, not globally
deduplicated physical sites. A future hierarchy/reconciliation model could make
these relationships explicit instead of relying on notes.

## Deliberately absent claims

The import assigns no facility ontology types, ecosystem ontology terms,
observed variables, dataset availability, opening dates, or operational status.
Project-wide research aims and planned instrumentation do not establish actual
site measurements. Existing validation bindings remain intact. Schema and
ontology validation still run through `just site`, including
`linkml-term-validator`; this import introduces no new ontology targets.

This is a reviewed curation pass, not an exhaustive inventory of every location
ever used by an NGEE-associated publication, nor a list of all later-phase
model-evaluation sites. Follow-up curation can add these with site-level evidence.

## Maintenance

Edit `db/curated/sites/ngee_arctic.yaml` and `ngee_tropics.yaml`, then run
`just site`. The normal builder incorporates them automatically. No imported
snapshots or generated database/HTML files were hand-edited. A direct HTTP client
request to the Arctic location server returned HTTP 403 during this review;
the accessible browser/search rendering was used for evidence. There is no
automated NGEE fetch command or complete raw HTML archive in this change.

# Danish WWTPs from Lücking et al. 2026 (Nucleocytoviricota network)

Curated 2026-10-24 from [Lücking, Manzano-Marín & Willemsen 2026, *ISME J*](https://doi.org/10.1093/ismejo/wrag267)
("Multilayered network analysis reveals the centrality of newly discovered
*Nucleocytoviricota* in wastewater treatment plant communities").
The OUP article and PDF returned HTTP 403; content was read from the
[bioRxiv preprint](https://doi.org/10.64898/2026.05.21.726523) and Crossref
abstract. Claims should be rechecked against the version of record when accessible.

## What the paper says about sites

- It analyses "23 metagenomes obtained from sequencing activated sludge samples
  collected from wastewater treatment plants in Denmark", reusing the Illumina,
  Nanopore and hybrid assemblies of
  [Singleton et al. 2021](https://doi.org/10.1038/s41467-021-22203-2), BioProject PRJNA629478.
- It recovers 61 nucleocytoviruses, 15 virophages and 14 polinton-like viruses (PLVs).
  Virophages/PLVs were found in 21 of 23 plants. Hirt (Hirtshals) had NCVs but no
  virophages/PLVs; AalW (Aalborg West) had PLVs without NCVs. Per-plant counts are
  in Fig. 2d and were not transcribed.
- Plant names are not listed in the text. Plant identity comes from the cited
  source: Singleton et al. received fresh activated sludge "from 23 Danish WWTP in
  August and September 2018", and PRJNA629478 contains exactly 23 `geo_loc_name`
  values, each with one Nanopore run from that 2018 sample.
- Derived data: [Zenodo 10.5281/zenodo.17735769](https://doi.org/10.5281/zenodo.17735769)
  (study-wide). ENA PRJEB105214 is registered (first public 2025-12-12) but returned
  no analyses or samples on 2026-10-24.

## Curation

- 22 new records in `db/curated/sites/wwtp_denmark_nucleocytovirus.yaml`; Aalborg
  West already existed (`wwtp_aalborg_west.yaml`, identical BioSample lat_lon) and was
  extended rather than duplicated.
- Coordinates, study code and verbatim ENA place name come from each plant's 2018
  Nanopore BioSample (`Site.evidence`). All runs for a code share one lat_lon; no datum
  is given. Display names restore Danish letters (Avedøre, Damhusåen, Egå, Ejby Mølle,
  Hjørring) and translate E/W/NE/NW; verbatim forms are aliases.
- `site_type` is ENVO wastewater treatment plant; activated sludge is recorded only
  as sample context, not as facility or ecosystem classification.
- One shared definition, `site_kb:variable-giant-virus-contig-recovery`
  (PARAMETER_GROUP, no ontology mapping asserted).
- The run inventory is archived at `db/raw/research/denmark_nucleocytovirus_ena.json`.
- No evidence quotations were added (bioRxiv was rate-limiting and OUP blocked),
  so these citations are not checked by `just validate-references`.

## Open questions

- Transcribe Fig. 2d per-plant NCV/virophage/PLV counts from the version of record.
- Identify the second plant lacking virophages/PLVs.
- Danish region (`state_province`) and operator names were not added.

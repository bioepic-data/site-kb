# DEIMS geometry issues (draft report)

Draft for the DEIMS-SDR maintainers, compiled 2026-11-06 from DEIMS API detail
records archived in `db/raw/deims/` (retrieved 2026-10-15). Not yet sent; whether
and how to report it is the project lead's decision. Site KB already works around
each issue (see `site-harmonization.md`), so nothing here blocks our build.

Method: each record's `attributes.geographic.boundaries` WKT polygon was reduced to
a bounding box and compared with its own `attributes.geographic.coordinates` point,
using a 0.01° (about 1 km) tolerance. Distances run from the point to the nearest
edge of the box. Boundary data outside our bounding box (polygon shape) was not
examined, so a point inside the box can still lie outside the polygon.

## 1. Boundaries that exclude the site's own point (34 records)

Offsets above about 10 km suggest a polygon from a different site or a coordinate
error. Offsets of 1–2 km may be a station point just outside a plot boundary, which
may be intended, but are listed for completeness.

| Offset (km) | DEIMS site | Point (lat, lon) | Boundary box (W, S, E, N) |
| ---: | --- | --- | --- |
| 2111.1 | [Jornada Experimental Range NEON - United States of America](https://deims.org/9a9e1cb0-c43d-463a-87f4-e44697739d1a) | 32.5907, -106.843 | -84.4965, 31.1722, -84.4453, 31.2138 |
| 309.5 | [Ecological research site of Mt. Jumbongsan - Korea (the Republic of)](https://deims.org/57fd3758-3470-4564-a6e5-61a41c8caf82) | 38.0174, 128.082 | 127.4492, 35.2472, 127.4829, 35.2760 |
| 245.5 | [Linze Inland River Basin Research Station - China](https://deims.org/b14f4ada-d4d5-4241-ae85-400b46b73da9) | 39.3333, 100.117 | 100.3470, 37.1238, 100.3542, 37.1333 |
| 139.9 | [Tarvisio FRI2 - Italy](https://deims.org/5907d0b6-7b4d-4260-a669-4bc0f61d1696) | 46.4894, 13.5933 | 11.4329, 46.2735, 11.7653, 46.5874 |
| 105.2 | [Sakaerat Environmental Research Station - Thailand](https://deims.org/ac2a24f6-47d2-43da-97c4-217e10e7fc1a) | 14.5, 100.867 | 101.8443, 14.4456, 101.9564, 14.5504 |
| 101.6 | [IT20 - Central Italy coastal dunes - Italy](https://deims.org/6d7ffd99-40e1-4f0d-ad26-6904581dbe9b) | 41, 13 | 12.0395, 41.9136, 15.1382, 42.1918 |
| 69.0 | [LTSER Neajlov catchment - Romania](https://deims.org/a6af4965-8352-461a-84b0-0cac30559ad7) | 45.1, 24.0667 | 24.8533, 43.9290, 26.2360, 44.8256 |
| 63.9 | [AusLTER - Three Parks Savanna Fire-Effects Plot Network - Australia](https://deims.org/16f934fe-e77d-4769-8baf-c247a3ad3b71) | -13.238, 132.276 | 132.1651, -14.3982, 132.7404, -13.8127 |
| 43.7 | [Lake Päijänne LTER - Finland](https://deims.org/28a399bc-e90f-43c2-a17d-2556b9644868) | 61.85, 25.48 | 25.7252, 62.2262, 26.7325, 62.6697 |
| 17.0 | [Functional connectivity and anthropogenic effects in agriculture landscapes: a case study in Brazilian Cerrado - Brazil](https://deims.org/feb5e8c8-ebcd-4066-a207-e506509071b6) | -16.593, -48.865 | -48.7052, -16.6014, -48.7038, -16.6001 |
| 12.0 | [West Polesie Biosphere Reserve - Poland](https://deims.org/0d769440-a36d-424b-8b32-1ae19812d72c) | 51.5083, 22.415 | 22.3800, 51.2000, 23.4000, 51.4000 |
| 7.3 | [IT07-Lagoons of Po River Delta - Italy](https://deims.org/b3ba9409-4953-446b-9890-5b977c4c1cb3) | 44.4836, 12.1919 | 12.0987, 44.5491, 12.3923, 44.8435 |
| 6.6 | [Centro Científico Huinay - Chile](https://deims.org/bd485f64-c61b-496a-afee-3712d346b1af) | -42.22, -72.25 | -72.4493, -42.4229, -72.0758, -42.2798 |
| 4.7 | [The Arid Iberian South East LTSER Platform - Spain](https://deims.org/889b159a-8b58-4685-9418-73ee70388799) | 37.0848, -2.2871 | -2.7300, 36.6700, -2.3400, 38.0300 |
| 4.3 | [River Spey at Fochabers - United Kingdom](https://deims.org/ba32773a-3ea9-425a-bfb5-5f2c7f49cbd2) | 57.6167, -3.1 | -4.6351, 56.8501, -3.0112, 57.5781 |
| 4.3 | [Baltimore Ecosystem Study LTER - United States of America](https://deims.org/c74174af-63ea-4783-9748-cabf980cdc22) | 39.2166, -76.6631 | -76.6873, 39.2551, -76.5459, 39.3529 |
| 2.5 | [Shenyang Experimental Station of Ecology - China](https://deims.org/5251a2c7-d44e-4ec1-892e-bf77b8bc3450) | 41.5167, 123.4 | 123.3638, 41.5162, 123.3699, 41.5199 |
| 2.5 | [LTSER Zone Atelier Antarctique - Antarctica](https://deims.org/5d621971-e68c-4015-b01f-a259f27dd6a0) | -67, 139 | 48.9092, -66.9776, 141.8849, -35.9041 |
| 2.3 | [Bälgsjön - Sweden](https://deims.org/063cd89b-59c9-43b1-bea2-2089cf90f521) | 59.5667, 14.9 | 14.8290, 59.5605, 14.8595, 59.5814 |
| 2.1 | [Taihu Laboratory for Lake Ecosystem Research - China](https://deims.org/cffcf04a-604c-41a2-9339-37822549995c) | 31.4, 120.217 | 120.2131, 31.4187, 120.2167, 31.4212 |
| 2.1 | [OZCAR-RI Glacioclim Zongo Glacier - Bolivia](https://deims.org/909de1ca-4845-46f4-9655-9ef172b454f1) | -16.25, -68.167 | -68.1544, -16.2832, -68.1277, -16.2640 |
| 1.7 | [Fengqiu Experimental Station for Agro-ecology Chinese Academy of Sciences - China](https://deims.org/5425446c-bfcb-448d-9f75-b06718df59ed) | 35.0167, 114.533 | 114.5516, 35.0163, 114.5544, 35.0206 |
| 1.7 | [Nørholm Hede - Denmark](https://deims.org/b356da08-15ac-42ad-ba71-aadb22845621) | 55.68, 8.61 | 8.5889, 55.6700, 8.5896, 55.6703 |
| 1.4 | [Akesu Water Balance Research Station - China](https://deims.org/2a58842f-e078-4450-a5dd-7b6f89ec83c1) | 40.6167, 80.85 | 80.8258, 40.6158, 80.8328, 40.6228 |
| 1.4 | [Sado Station of Niigata University Forest - Japan](https://deims.org/3eeb2941-68a2-4252-8e05-0b1deb9be1eb) | 38.2, 138.433 | 138.4456, 38.2081, 138.4593, 38.2256 |
| 1.4 | [Fukang Desert Ecological Research Station - China](https://deims.org/7e840801-4a73-4c93-9f11-62e8db5f0329) | 44.2833, 87.9167 | 87.9307, 44.2911, 87.9459, 44.2955 |
| 1.3 | [Taoyuan Agricultural Ecological Station - China](https://deims.org/9518c7f8-d3f2-4e57-b6a7-67bb4a20f1e5) | 28.9167, 111.433 | 111.4379, 28.9279, 111.4432, 28.9315 |
| 1.3 | [Lysina & Pluhuv Bor catchments - Czechia](https://deims.org/a7cf7d23-ffa1-45f0-bb3b-82ee8fdf725a) | 50.0333, 12.6514 | 12.6695, 49.9983, 12.7885, 50.0623 |
| 1.2 | [Ecological research site of Fujinitayama - Japan](https://deims.org/c470ad34-31d9-41c2-837b-0dfc8ecab70d) | 36.9167, 139.967 | 139.9534, 36.9235, 139.9566, 36.9264 |
| 1.1 | [Engure marine site - Latvia](https://deims.org/3706b1ea-2aad-4363-bf4d-ba3ccba584e6) | 57.357, 23.14 | 23.1331, 57.3366, 23.1669, 57.3468 |
| 1.1 | [National Park Schleswig-Holstein Wadden Sea - Germany](https://deims.org/f1e16c20-c13e-426a-97ed-d865919bd7a4) | 54.3167, 8.93333 | 8.2171, 53.8659, 8.9165, 55.0456 |
| 1.0 | [Mont Avic Gloria (IT19 Aosta Valley) - Italy](https://deims.org/54cd5daf-f7d8-4af8-8e0c-974ff44fdf83) | 45.65, 7.6 | 7.5450, 45.6330, 7.5867, 45.6557 |
| 1.0 | [Sanjiang Plain Marsh Ecological Experimental Station - China](https://deims.org/c9ba2a84-6fb3-4061-a9ec-529954b948c8) | 47.5833, 133.517 | 133.4879, 47.5763, 133.5043, 47.5944 |
| 0.8 | [Velika Morava - Serbia](https://deims.org/5bc9428a-46e2-48c3-beb5-aec13d06f0fe) | 43.7547, 21.3936 | 21.0896, 43.7515, 21.3835, 44.5800 |

Notable cases:

- Jornada Experimental Range NEON: the boundary is identical to The Jones Center At
  Ichauway NEON (Georgia), about 2,100 km away (see section 2).
- Tarvisio FRI2 and Lake Päijänne LTER were also flagged in site-kb PR #5 review:
  their boxes lie about 140 km and 44 km from their own points.

## 2. Records sharing an identical boundary (10 pairs)

Some pairs are probably the same site registered twice; others look like a boundary
copied to a neighbouring site. Each pair needs a maintainer's judgement.

| Record A | Record B |
| --- | --- |
| [Nant Teyrn - United Kingdom](https://deims.org/11dbfa58-3951-4e9a-b2e0-1d5d4fbfe8b3) | [Yr Wyddfa/Snowdon - United Kingdom](https://deims.org/8b5da977-eed8-459f-b663-f3835aa0b356) |
| [Glensaugh - United Kingdom](https://deims.org/1c4d454d-0c00-49f9-a7fe-3a3e596c3648) | [Birnie Burn - United Kingdom](https://deims.org/8747ccf7-52af-4a83-a558-71a768b81a30) |
| [The Jones Center At Ichauway NEON - United States of America](https://deims.org/2592b8ed-e6cf-4854-9488-e9459b9b458c) | [Jornada Experimental Range NEON - United States of America](https://deims.org/9a9e1cb0-c43d-463a-87f4-e44697739d1a) |
| [Balaton LTSER - Hungary](https://deims.org/30e906bb-7ed6-4fee-8ae9-539db55dfd35) | [Lake Balaton LTER Site, Balaton LTER - Hungary](https://deims.org/32f08dc2-9cef-4a03-9d29-912fa2719224) |
| [Stubai (combination of Neustift meadows and Kaserstattalm) - Austria](https://deims.org/324f92a3-5940-4790-9738-5aa21992511c) | [eLTER Tyrolean Mountain Grassland and -Forest - Austria](https://deims.org/8bbe7b71-df6a-48db-b9ad-01a3e0fae0f9) |
| [Cairngorms (ECN site) - United Kingdom](https://deims.org/5a04fee1-42aa-47e9-abfc-043a3eda12ac) | [Allt a'Mharcaidh - United Kingdom](https://deims.org/b7f692ef-10b0-432e-ab42-a3e9b764c5cc) |
| [Gesäuse-Johnsbachtal - Austria](https://deims.org/5c2dc483-1ad3-47a3-992c-d73d42301a74) | [Johnsbachtal - Austria](https://deims.org/b3ecdade-2c03-4ef2-85fe-e9c8f9e65a84) |
| [VLIZ Marine Observatory - Belgium](https://deims.org/7c1cb7b8-8635-4d9c-8cb3-61559c8a66bc) | [Belgian coastal waters and sand bank systems - Belgium](https://deims.org/e83a90a3-2fb4-49bc-8991-a1d5b017ae19) |
| [Loch Davan - United Kingdom](https://deims.org/7e685712-5b3f-40e2-86fa-14125260efa1) | [Loch Kinord - United Kingdom](https://deims.org/9fa171d2-5a24-40d3-9c06-b3f9e9d0f270) |
| [The UNESCO/UNEP the Pilica River Demonstration Site - Poland](https://deims.org/8c19445a-ed76-43b8-acfb-4cc18e3fd8b3) | [The Pilica River LTER - Poland](https://deims.org/c79080ec-07ec-4c1e-a567-286ba1631405) |

## 3. NEON-linked records disagreeing with NEON coordinates

NEON's API lists these DEIMS IDs for its sites; NEON's own coordinates were compared.

- Black Warrior River NEON (BLWA): the DEIMS point (31.85388, -88.16122) matches
  NEON's Lower Tombigbee (TOMB) site, about 80 km from NEON's BLWA point
  (32.541529, -87.798151).
- Blandy Experimental Farm NEON (BLAN): the DEIMS point (39.094908, -77.979278) and
  boundary lie about 8 km from NEON's BLAN point (39.033698, -78.041788); the box
  excludes both NEON's point and the NEON AmeriFlux tower US-xBL (39.0603, -78.0716),
  so it may cover only part of the site.


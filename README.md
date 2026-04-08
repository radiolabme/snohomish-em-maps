# Snohomish County Emergency Management Maps

Open-data GIS maps for emergency management, hazard analysis, and search & rescue operations in Snohomish County, Washington.

**11 maps. Zero proprietary data. One command.**

All maps pull from authoritative public sources (FEMA, USGS, US Census, WA DNR, WSDOT, Snohomish County GIS, OpenStreetMap) and share a common scale, grid, and projection so they can be compared side by side or overlaid.

---

## Quick start

```bash
# See what's available
./generate.py

# Generate one map
./generate.py combined

# Generate everything (~15 min on first run, cached after)
./generate.py all

# Open a map
./generate.py open combined

# Run tests
./generate.py test
```

### Requirements

```bash
pip install geopandas matplotlib adjustText pillow
```

Python 3.10+. No API keys needed — all data sources are public.

---

## The maps

### Overview

| Map | What it shows | Why it matters |
|-----|--------------|----------------|
| `state` | Washington State with Snohomish highlighted | Context — where the county sits |
| `combined` | All hazards + roads + cities + terrain | The "one map to rule them all" for briefings |

### Hazard layers

| Map | What it shows | Why it matters |
|-----|--------------|----------------|
| `flood` | FEMA flood zones by risk level | 63% of county population is in high-risk zones |
| `volcanic` | Glacier Peak lahar paths, tephra zone | Lahars follow the Stillaguamish & Sauk river valleys |
| `services` | 18 fire districts, 3 hospital districts | Response jurisdiction boundaries |
| `water` | Diking, drainage, flood control districts | Who manages what infrastructure |

### Operational maps

| Map | What it shows | Why it matters |
|-----|--------------|----------------|
| `facilities` | 9 hospitals, 70 fire stations, 243 schools, 20 police | Eastern wilderness has zero facilities |
| `terrain` | 4,636 trails, 2,904 forest roads on hillshade | Core SAR planning map |
| `population` | Census block-group density + hazard overlay | Shows who needs evacuating and from what |
| `evacuation` | Roads by capacity + 16 bottleneck segments | SR-530 to Darrington is the critical vulnerability |
| `rivers` | 19,705 waterways, 64 boat ramps, 13 major rivers | Swift water rescue access planning |

---

## Key findings from the data

- **524,479 people** (63.3%) live in FEMA high-risk flood zones
- **52,392 people** (6.3%) live in lahar inundation zones
- **SR-530** (Oso/Darrington corridor) is a single-route bottleneck through both flood and lahar zones — if cut, Darrington is isolated
- The **eastern half** of the county (Cascade foothills, wilderness) has virtually no emergency facilities
- **64 boat ramps** are available across the river system for swift water operations

---

## Project structure

```
generate.py              CLI entry point (run ./generate.py --help)
snohomish_base.py        Shared infrastructure (constants, helpers, layout)
snohomish_combined.py    Combined hazard & infrastructure map
snohomish_flood_zones.py FEMA flood zones
snohomish_volcanic.py    Volcanic / lahar hazards
snohomish_emergency_services.py  Fire & hospital districts
snohomish_water_mgmt.py  Water management districts
snohomish_facilities.py  Critical facilities (OSM)
snohomish_terrain.py     Terrain, trails & SAR access
snohomish_population.py  Population density & exposure
snohomish_evacuation.py  Evacuation routes & bottlenecks
snohomish_rivers.py      River systems & water access
wa_counties_map.py       Washington State overview

test_wa_counties_map.py       Tests for state map
test_snohomish_maps.py        Tests for individual maps
test_snohomish_combined.py    Tests for combined map
conftest.py                   Pytest configuration
```

Each map script produces both **PNG** (200 DPI, ~14m ground resolution) and **SVG** output.

---

## Data sources

| Source | What | Endpoint |
|--------|------|----------|
| US Census TIGER/Line | County boundaries, block groups | census.gov |
| FEMA NFHL | Flood hazard zones | hazards.fema.gov |
| WA DNR | Volcanic hazards, landslide data | gis.dnr.wa.gov |
| Snohomish County GIS | Districts, city boundaries, national forest | gis.snoco.org |
| WSDOT | State routes, road classification | data.wsdot.wa.gov |
| USGS | Hillshade terrain, NHD river data | nationalmap.gov |
| Natural Earth | Coastline, lakes (10m resolution) | naciscdn.org |
| OpenStreetMap | Facilities, trails, boat ramps | overpass-api.de |
| WA State Parks | Park boundaries | arcgis.com |

All data is fetched via REST APIs and cached locally in `/tmp`. No downloads required beyond `pip install`.

---

## Common scale

All Snohomish County maps share:

- **Projection**: EPSG:2855 (NAD83 / Washington North)
- **Extent**: 372,000–502,000 E, 74,000–150,000 N
- **Grid**: 10 km spacing
- **Ground resolution**: ~14 m/pixel at 200 DPI

Maps can be overlaid directly in any GIS tool or image editor.

---

## License

The code is provided as-is. All underlying data is from US government and open-data sources with no usage restrictions.

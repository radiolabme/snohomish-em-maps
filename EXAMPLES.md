# Example outputs

Pre-generated PNG and SVG map images are included in the `examples/` directory so you can see what the project produces without running anything.

To regenerate these yourself: `./generate.py all`

## Maps

### State overview

| File | Description |
|------|-------------|
| `washington_counties.png` | Washington State with all 39 counties labeled, Snohomish highlighted in blue |

### Hazard layers

| File | Description |
|------|-------------|
| `snohomish_flood_zones.png` | FEMA flood hazard zones — red (high risk), orange (moderate), gray (minimal) |
| `snohomish_volcanic.png` | Glacier Peak & Mt Baker lahars (purple), near-volcano hazards, tephra zone |
| `snohomish_emergency_services.png` | 18 fire protection districts + 3 hospital districts |
| `snohomish_water_mgmt.png` | Diking, drainage, and flood control district boundaries |

### Combined & operational maps

| File | Description |
|------|-------------|
| `snohomish_combined.png` | All hazards + roads + cities + public lands + hillshade terrain |
| `snohomish_facilities.png` | 9 hospitals, 70 fire stations, 243 schools, 20 police stations |
| `snohomish_terrain.png` | 4,636 trails and 2,904 forest roads on hillshade — SAR planning map |
| `snohomish_population.png` | Population density choropleth with flood/lahar exposure overlay |
| `snohomish_evacuation.png` | Roads by capacity, 16 bottleneck segments, 4 annotated critical points |
| `snohomish_rivers.png` | 19,705 waterways, 64 boat ramps, 13 labeled major rivers |

## SVG versions

SVG versions are included for maps with reasonable file sizes. Maps with very dense geometry (rivers, flood zones, terrain) produce SVGs in the 15–30 MB range and are excluded from the repository — generate them locally with `./generate.py`.

## Notes

These images were generated from live government data sources as of April 2026. Data may change as agencies update their published layers. Regenerate with `./generate.py all` to get the latest data.

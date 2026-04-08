# How this project was built

This document explains the approach, tools, and decisions behind this map set so you can replicate it, extend it, or build something similar for your own county or region.

---

## The short version

We wrote Python scripts that pull free geographic data from government REST APIs, combine the layers using GeoPandas, and render them with Matplotlib. There is no GIS desktop software involved, no paid subscriptions, and no manual data downloads. Everything runs from the command line.

The total cost is zero dollars. The total setup time is about five minutes.

---

## What you need

### Software

| Tool | What it does | Install |
|------|-------------|---------|
| **Python 3.10+** | Runs everything | [python.org](https://www.python.org/downloads/) or your OS package manager |
| **pip** | Installs Python packages | Comes with Python |

That's it. Everything else is a Python package.

### Python packages

```bash
pip install geopandas matplotlib adjustText pillow
```

This pulls in the dependencies automatically (shapely, pyproj, pandas, numpy, etc.). No conda environment or virtual environment is strictly required, though using one is good practice.

### Hardware

Any modern laptop. The scripts use 1–2 GB of RAM at peak (the river map with 58,000 stream segments is the heaviest). A full regeneration of all 11 maps takes about 15 minutes, mostly spent waiting on network requests to government APIs.

### No API keys

Every data source used in this project is freely accessible without authentication. No accounts, no tokens, no rate-limit keys.

---

## The approach

### 1. Start with a reliable base map

The foundation is the US Census Bureau's TIGER/Line county shapefile. It's the authoritative source for county boundaries in the United States and it's updated annually. We filter it to Snohomish County (FIPS code 53061) and reproject it to EPSG:2855 (NAD83 / Washington State Plane North), which gives us coordinates in meters — useful for scale bars and distance measurements.

The coastline comes from Natural Earth's 10-meter land polygons. We clip the county boundary to the coastline so that Puget Sound, the Strait of Juan de Fuca, and river estuaries show as water rather than as county fill. This is important — without it, county boundaries extend over water and make the geography confusing.

### 2. Layer data from authoritative sources

Each map layer comes from a government or community REST API. The pattern is always the same:

1. **Query** the API with a bounding box filter (Snohomish County's extent)
2. **Receive** GeoJSON features
3. **Reproject** to the common coordinate system (EPSG:2855)
4. **Clip** to the county boundary
5. **Render** on top of the base map

The key data sources:

- **FEMA National Flood Hazard Layer** — flood zones classified by risk level (A, AE, VE, X, etc.). Accessed via ArcGIS REST API with pagination (the service limits responses to 2,000 features at a time).
- **WA Department of Natural Resources** — volcanic hazard zones (lahars, tephra, near-volcano hazards) compiled from USGS assessments. Also provides the statewide landslide inventory.
- **Snohomish County GIS** — fire districts, hospital districts, water management districts, city boundaries, national forest boundary. All served from a single ArcGIS MapServer with numbered layers.
- **WSDOT** — state route centerlines with route classification (interstate, US highway, state route).
- **USGS National Map** — hillshade terrain (raster export from the Shaded Relief MapServer) and the National Hydrography Dataset for rivers and streams.
- **OpenStreetMap via Overpass API** — point locations for hospitals, fire stations, schools, police stations, boat ramps, and trail networks. This fills gaps where government sources don't publish facility-level point data.
- **US Census Bureau** — block group boundaries with population counts, used for the exposure analysis.

### 3. Enforce a common scale and layout

Every map uses the same fixed extent, projection, and layout grid. This means you can flip between maps and features stay in the same position. It also means you can overlay maps in an image editor or GIS tool and they align perfectly.

The layout has defined zones: the map content area, a footer with a scale bar (left), legend (center), and data attribution (bottom). These positions are defined as constants in the shared base module so every map places its chrome in the same spot.

### 4. Handle real-world data problems

Government GIS data is not always clean. Some issues we encountered and solved:

- **Invalid geometries**: Coastline polygons from Natural Earth sometimes have self-intersections. We apply `make_valid()` and `buffer(0)` to fix topology before any spatial operations.
- **Coordinate system distortion**: Natural Earth's continent-scale polygons become wildly distorted when reprojected to a state-plane CRS. We clip them to the Pacific Northwest bounding box in WGS84 *before* reprojecting.
- **Mispositioned data**: The WA State Parks boundary for Everett Jetty was offset ~3 km from the real location. We filter out small parks (under 500 acres) that render as confusing artifacts at county scale.
- **Color collisions**: Our initial color scheme used the same red for flood zones and near-volcano hazards, making Glacier Peak look like a flood zone. We switched volcanic hazards to a purple palette.
- **Overlapping labels**: Dense urban areas in southwest Snohomish County (Lynnwood, Edmonds, Mountlake Terrace, Woodway, Brier) had label collisions. We use the `adjustText` library to automatically separate them with leader lines.

### 5. Test the output

The test suite (82 tests) validates three things:

- **Data integrity**: Do the REST APIs still return data? Are the expected fields present?
- **Rendering correctness**: Does the map have the right title, legend entries, scale bar? Are all counties/cities labeled?
- **Visual content**: Does the PNG contain the expected colored pixels? (Red for flood zones, blue for interstates, green for forests, etc.)

This catches regressions if an upstream API changes its schema or goes offline.

---

## How to replicate this for a different county

1. **Change the FIPS code.** Snohomish County is FIPS 53061 (state 53, county 061). Find your county's code at [census.gov](https://www.census.gov/library/reference/code-lists/ansi.html). Update the filter in `load_snohomish_boundary()`.

2. **Change the projection.** EPSG:2855 is specific to Washington State (north zone). Find the appropriate State Plane or UTM zone for your area at [spatialreference.org](https://spatialreference.org/).

3. **Update the map extent.** The `MAP_XLIM` and `MAP_YLIM` constants define the fixed map view. Set them to your county's bounds plus padding.

4. **Adjust the data sources.** FEMA, Census, USGS, NHD, and Natural Earth are national — they work everywhere in the US without changes. State-level sources (WA DNR, WSDOT, SnoCoWA GIS) will need to be replaced with your state and county equivalents. Most states publish similar data through ArcGIS REST services; search `[your state] GIS open data` to find them.

5. **Adjust the Overpass queries.** Change the bounding box coordinates in the Overpass API queries to your county's extent.

The shared base module (`snohomish_base.py`) is designed to make this straightforward — most of the county-specific values are constants at the top of the file.

---

## Why these tools and not a GIS application

Desktop GIS software (ArcGIS Pro, QGIS) is powerful but introduces complexity that isn't necessary for this use case:

- **Reproducibility**: A Python script produces the same output every time. A GIS project file depends on data paths, plugin versions, and manual layer styling that's hard to replicate on another machine.
- **Automation**: Regenerating all 11 maps is one command. In a desktop GIS, it's 11 manual export workflows.
- **Version control**: Python scripts are plain text — they diff cleanly, merge cleanly, and fit in a git repository. GIS project files are opaque binaries.
- **Cost**: Python, GeoPandas, and Matplotlib are free. ArcGIS Pro is $100+/month.

The tradeoff is that Python maps require more upfront code to get the styling right. For a one-off map, QGIS is faster. For a maintained set of maps that need to be regenerated as data updates, scripted maps win.

---

## What this project does not do

- **Real-time data**: These are static maps built from the latest available published data. They do not connect to live sensor feeds, weather alerts, or incident management systems.
- **Interactive maps**: The output is PNG and SVG images, not a web map. For interactive use, the same data sources could feed a Leaflet or Mapbox application.
- **Predictive modeling**: The population exposure numbers are simple spatial intersections (does this block group overlap a hazard zone?), not hydraulic models or evacuation simulations.
- **Authoritative hazard assessment**: These maps visualize published government data. They are not a substitute for official FEMA flood studies, USGS volcanic hazard assessments, or county-adopted hazard mitigation plans.

---

## Further reading

- [FEMA National Flood Hazard Layer](https://www.fema.gov/flood-maps/national-flood-hazard-layer) — how flood zones are delineated and what the zone codes mean
- [USGS Volcano Hazards Program — Glacier Peak](https://www.usgs.gov/volcanoes/glacier-peak) — lahar modeling and eruption history
- [Snohomish County Hazard Viewer](https://storymaps.arcgis.com/collections/28d8e2c49c6a406b875ed20fad52139a) — the county's own interactive hazard maps
- [WA DNR Landslide Inventory](https://fortress.wa.gov/dnr/geologydata/publications/ger_ri43_snohomish_county_landslide_inventory.pdf) — the lidar-derived inventory (6,171 mapped landslides)
- [GeoPandas documentation](https://geopandas.org/) — the core library for vector GIS in Python
- [ArcGIS REST API reference](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/) — how to query the government MapServer endpoints used throughout this project

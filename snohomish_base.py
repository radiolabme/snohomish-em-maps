"""
Shared infrastructure for Snohomish County emergency management maps.
Provides: county boundary, coastline clipping, consistent styling, REST query helpers.
"""

import functools
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
from matplotlib.patches import Patch
from shapely.errors import GEOSException
from shapely.geometry import box, Point, Polygon, MultiPolygon, LineString, MultiLineString
from shapely.ops import unary_union
from shapely.validation import make_valid

# Constants

TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2023/COUNTY/tl_2023_us_county.zip"
NE_LAND_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip"
TARGET_CRS = "EPSG:2855"
PNW_BBOX_WGS84 = (-130, 44, -116, 50)

WATER_COLOR = "#B3D4F0"
LAND_BG = "#F5F5F2"
SNOHOMISH_GRAY = "#E8E8E8"
SNOHOMISH_EDGE = "#444444"

# Standard figure size for all maps
FIG_SIZE = (20, 16)
DPI = 200

# Layout grid (all Y values in EPSG:2855 meters)
# County bounds: x=[379412, 494492]  y=[86666, 145555]
#
#  150,000 ┬─── MAP_YLIM top (4.4km above county)
#          │  county map content
#   86,666 │─── county southern edge
#          │  3.3km gap
#   83,000 │─── FOOTER_SCALE_Y: scale bar
#          │  1km gap
#   81,500 │─── FOOTER_LEGEND_Y: legend top
#          │  legend height (~5-7km depending on rows)
#   74,500 │─── FOOTER_ATTR_Y: data attribution text
#          │  0.5km gap
#   74,000 ┴─── MAP_YLIM bottom
#
MAP_XLIM = (372_000, 502_000)
MAP_YLIM = (74_000, 150_000)

FOOTER_SCALE_Y  = 83_000   # scale bar center Y
FOOTER_LEGEND_Y = 81_500   # legend bbox_to_anchor top Y
FOOTER_ATTR_Y   = 74_500   # attribution text Y

# Shared service URLs

FEMA_NFHL_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
VOLCANIC_URL = (
    "https://gis.dnr.wa.gov/site1/rest/services/"
    "Public_Geology/Volcanic_Hazards/MapServer"
)
SNOCO_DISTRICTS_URL = (
    "https://gis.snoco.org/sis/rest/services/"
    "Districts/Districts_and_Boundaries/MapServer"
)
WSDOT_ROUTES_URL = (
    "https://data.wsdot.wa.gov/arcgis/rest/services/"
    "Shared/StateRoutes/MapServer"
)
WA_STATE_PARKS_URL = (
    "https://services5.arcgis.com/4LKAHwqnBooVDUlX/arcgis/rest/services/"
    "ParkBoundaries/FeatureServer"
)
NHD_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Layer IDs
FEMA_FLOOD_LAYER = 28
VOLCANIC_LAYER = 0
SNOCO_CITIES_LAYER = 13
SNOCO_FIRE_LAYER = 31
SNOCO_HOSPITAL_LAYER = 33
SNOCO_FOREST_LAYER = 34
SNOCO_DIKING_LAYER = 38
SNOCO_DRAINAGE_LAYER = 39
SNOCO_FLOOD_CTRL_LAYER = 40
NHD_FLOWLINES_LAYER = 6
NHD_WATERBODIES_LAYER = 12

# Shared color palette

HIGH_RISK_COLOR = "#E53E3E"
MODERATE_RISK_COLOR = "#F6AD55"
LAHAR_COLOR = "#AB47BC"
NEAR_VOLCANO_COLOR = "#7B1FA2"
TEPHRA_COLOR = "#CE93D8"
NATIONAL_FOREST_COLOR = "#C5E6B8"
STATE_PARK_COLOR = "#4CAF50"
INTERSTATE_COLOR = "#1565C0"
US_HIGHWAY_COLOR = "#D84315"
STATE_ROUTE_COLOR = "#555555"

HIGH_RISK_ZONES = {"A", "AE", "AH", "AO", "V", "VE"}

# Shared text effects

TEXT_HALO = [pe.withStroke(linewidth=3, foreground="white")]
TEXT_HALO_BOLD = [pe.withStroke(linewidth=4, foreground="white")]

# Overpass bbox for Snohomish County (lat_min, lon_min, lat_max, lon_max)
OVERPASS_BBOX = (47.78, -122.46, 48.30, -120.91)

# Font setup

def setup_fonts():
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 14,
    })


# Caching helper

def fetch_cached(url, name):
    local = os.path.join(tempfile.gettempdir(), name)
    if not os.path.exists(local):
        print(f"  Downloading {name}...")
        urllib.request.urlretrieve(url, local)
    return local


# Load Snohomish County boundary


@functools.lru_cache(maxsize=1)
def load_snohomish_boundary():
    """Return Snohomish County as a single-row GeoDataFrame in EPSG:2855."""
    local_zip = fetch_cached(TIGER_URL, "tl_2023_us_county.zip")
    gdf = gpd.read_file(f"zip://{local_zip}", bbox=(-123, 47, -120, 49))
    sno = gdf[(gdf["STATEFP"] == "53") & (gdf["NAME"] == "Snohomish")].copy()
    sno = sno.to_crs(TARGET_CRS)
    return sno


@functools.lru_cache(maxsize=1)
def get_snohomish_bbox_wgs84():
    """Return (xmin, ymin, xmax, ymax) in WGS84 for Snohomish County."""
    local_zip = fetch_cached(TIGER_URL, "tl_2023_us_county.zip")
    gdf = gpd.read_file(f"zip://{local_zip}", bbox=(-123, 47, -120, 49))
    sno = gdf[(gdf["STATEFP"] == "53") & (gdf["NAME"] == "Snohomish")]
    b = sno.total_bounds
    return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))


# Natural Earth coastline clipping

def load_land_clipped():
    """Load NE 10m land, clipped to PNW in WGS84, reprojected."""
    local_zip = fetch_cached(NE_LAND_URL, "ne_10m_land.zip")
    land = gpd.read_file(f"zip://{local_zip}", bbox=PNW_BBOX_WGS84)
    pnw_box = box(*PNW_BBOX_WGS84)
    land = land.copy()
    land["geometry"] = land.geometry.apply(
        lambda g: make_valid(make_valid(g).intersection(pnw_box))
    )
    land = land[~land.geometry.is_empty]
    land = land.to_crs(TARGET_CRS)
    return land


def clip_to_land(gdf, land):
    """Clip a GeoDataFrame to land (remove water areas)."""
    bounds = gdf.total_bounds
    pad = 5_000
    bbox_geom = box(bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)

    land_copy = land.copy()
    land_copy["geometry"] = land_copy.geometry.apply(lambda g: make_valid(g).buffer(0))
    land_local = land_copy[land_copy.intersects(bbox_geom)].copy()
    land_local["geometry"] = land_local.geometry.apply(
        lambda g: make_valid(g.intersection(bbox_geom)).buffer(0)
    )
    land_union = make_valid(unary_union(land_local.geometry)).buffer(100)

    result = gdf.copy()
    result["geometry"] = result.geometry.apply(lambda g: make_valid(g).buffer(0))
    result["geometry"] = result.geometry.apply(
        lambda g: _extract_polygons(make_valid(g.intersection(land_union)))
    )
    return result[~result.geometry.is_empty]


def _extract_polygons(geom):
    """Extract only Polygon/MultiPolygon parts from a geometry."""
    if geom.is_empty:
        return geom
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    polys = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon))]
    return make_valid(unary_union(polys)) if polys else Polygon()


def _extract_lines(geom):
    """Extract only LineString/MultiLineString parts from a geometry."""
    if geom.is_empty:
        return geom
    if isinstance(geom, (LineString, MultiLineString)):
        return geom
    lines = [g for g in geom.geoms if isinstance(g, (LineString, MultiLineString))]
    return unary_union(lines) if lines else LineString()


# County clipping helpers

def clip_to_county(gdf, county_gdf):
    """Clip polygon features to the county boundary."""
    if gdf.empty:
        return gdf
    county_union = make_valid(unary_union(county_gdf.geometry)).buffer(0)
    result = gdf.copy()
    result["geometry"] = result.geometry.apply(lambda g: make_valid(g).buffer(0))
    result["geometry"] = result.geometry.apply(
        lambda g: _extract_polygons(make_valid(g.intersection(county_union)))
    )
    return result[~result.geometry.is_empty]


def clip_lines_to_county(gdf, county_gdf):
    """Clip line features to the county boundary."""
    if gdf.empty:
        return gdf
    county_union = make_valid(unary_union(county_gdf.geometry)).buffer(0)
    result = gdf.copy()
    result["geometry"] = result.geometry.apply(
        lambda g: make_valid(g).intersection(county_union)
    )
    return result[~result.geometry.is_empty]


# Overpass API helpers

def query_overpass(query, retries=3):
    """Query the Overpass API with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            data = urllib.parse.urlencode({"data": query}).encode()
            req = urllib.request.Request(
                OVERPASS_URL, data=data,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp = urllib.request.urlopen(req, timeout=120)
            return json.loads(resp.read())
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
            print(f"  Overpass attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(5 * attempt)
    return {"elements": []}


def overpass_to_points_gdf(result, county_geom=None):
    """Convert Overpass JSON result to a GeoDataFrame of points, optionally clipped."""
    points = []
    for elem in result.get("elements", []):
        lat = elem.get("lat") or elem.get("center", {}).get("lat")
        lon = elem.get("lon") or elem.get("center", {}).get("lon")
        if lat and lon:
            points.append({
                "geometry": Point(lon, lat),
                "name": elem.get("tags", {}).get("name", ""),
            })
    if not points:
        return gpd.GeoDataFrame()
    gdf = gpd.GeoDataFrame(points, crs="EPSG:4326").to_crs(TARGET_CRS)
    if county_geom is not None:
        gdf = gdf[gdf.geometry.within(county_geom)]
    return gdf


def classify_flood_risk(row):
    """Classify a FEMA flood zone row into risk categories."""
    zone = str(row.get("FLD_ZONE", "")).strip().upper()
    if zone in HIGH_RISK_ZONES:
        return "high"
    if zone == "X":
        subtype = str(row.get("ZONE_SUBTY", "")).strip()
        if "0.2" in subtype:
            return "moderate"
        return "minimal"
    if zone == "D":
        return "other"
    return "other"


def find_name_column(gdf, candidates=None):
    """Find the first matching name column in a GeoDataFrame."""
    if candidates is None:
        candidates = ["NAME", "FULL_NAME", "ParkName", "LABEL", "name", "Name"]
    for c in candidates:
        if c in gdf.columns:
            return c
    return None


# Raster export helper

HILLSHADE_URL = (
    "https://basemap.nationalmap.gov/arcgis/rest/services/"
    "USGSShadedReliefOnly/MapServer"
)


def fetch_hillshade(bbox_wgs84, width=2600, height=1400):
    """Fetch USGS shaded relief as a numpy array for imshow().

    Returns (img_array, extent) where extent = [xmin, xmax, ymin, ymax] in
    EPSG:2855 suitable for ax.imshow(..., extent=extent).
    """
    import io
    from PIL import Image as PILImage

    cache_path = os.path.join(
        tempfile.gettempdir(),
        f"hillshade_{width}x{height}.png",
    )
    if not os.path.exists(cache_path):
        params = urllib.parse.urlencode({
            "bbox": f"{bbox_wgs84[0]},{bbox_wgs84[1]},{bbox_wgs84[2]},{bbox_wgs84[3]}",
            "bboxSR": "4326",
            "imageSR": "2855",
            "size": f"{width},{height}",
            "format": "png",
            "f": "image",
        })
        url = f"{HILLSHADE_URL}/export?{params}"
        print(f"  Fetching hillshade ({width}x{height})...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=60)
        with open(cache_path, "wb") as f:
            f.write(resp.read())
    else:
        print("  Using cached hillshade...")

    img = PILImage.open(cache_path).convert("RGBA")
    img_arr = np.array(img)

    # Extent in EPSG:2855 — match the fixed map extent
    extent = [MAP_XLIM[0], MAP_XLIM[1], MAP_YLIM[0], MAP_YLIM[1]]
    return img_arr, extent


# REST query helper

def query_arcgis_rest(base_url, layer_id, bbox_wgs84=None, where="1=1",
                      out_fields="*", max_records=2000):
    """Query an ArcGIS MapServer layer and return a GeoDataFrame.

    Handles pagination for large result sets.
    """
    url = f"{base_url}/{layer_id}/query"
    all_features = []
    offset = 0

    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "f": "geojson",
            "outSR": "4326",
            "resultOffset": str(offset),
            "resultRecordCount": str(max_records),
        }
        if bbox_wgs84:
            params["geometry"] = f"{bbox_wgs84[0]},{bbox_wgs84[1]},{bbox_wgs84[2]},{bbox_wgs84[3]}"
            params["geometryType"] = "esriGeometryEnvelope"
            params["inSR"] = "4326"
            params["spatialRel"] = "esriSpatialRelIntersects"

        query_url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(query_url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())

        if "features" not in data:
            print(f"  Warning: no features in response for layer {layer_id}")
            break

        features = data["features"]
        all_features.extend(features)
        print(f"  Fetched {len(features)} features (total: {len(all_features)})")

        if len(features) < max_records:
            break
        offset += max_records

    if not all_features:
        return gpd.GeoDataFrame()

    geojson = {"type": "FeatureCollection", "features": all_features}
    gdf = gpd.GeoDataFrame.from_features(geojson, crs="EPSG:4326")
    gdf = gdf.to_crs(TARGET_CRS)
    return gdf


# Base map rendering

def create_base_map(sno_boundary, land=None, title="Snohomish County"):
    """Create a figure with Snohomish County outline, water bg, and land bg.

    Returns (fig, ax, sno_clipped) where sno_clipped is the land-clipped boundary.
    """
    setup_fonts()
    fig, ax = plt.subplots(1, 1, figsize=FIG_SIZE, facecolor="white")
    ax.set_facecolor(WATER_COLOR)

    sno_clipped = sno_boundary
    if land is not None:
        # Draw surrounding land
        bounds = sno_boundary.total_bounds
        pad = 10_000
        bbox_geom = box(bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)
        land_copy = land.copy()
        land_copy["geometry"] = land_copy.geometry.apply(lambda g: make_valid(g).buffer(0))
        land_local = land_copy[land_copy.intersects(bbox_geom)].copy()
        land_local["geometry"] = land_local.geometry.apply(
            lambda g: make_valid(g.intersection(bbox_geom)).buffer(0)
        )
        land_bg = gpd.GeoDataFrame(
            geometry=[make_valid(unary_union(land_local.geometry)).buffer(0)],
            crs=TARGET_CRS,
        )
        land_bg.plot(ax=ax, color=LAND_BG, edgecolor="none")
        sno_clipped = clip_to_land(sno_boundary, land)

    # County fill and border
    sno_clipped.plot(ax=ax, color=SNOHOMISH_GRAY, edgecolor=SNOHOMISH_EDGE, linewidth=1.2)

    # Fixed extent — shared across all maps for consistent scale
    ax.set_xlim(*MAP_XLIM)
    ax.set_ylim(*MAP_YLIM)

    ax.set_title(title, fontsize=20, fontweight="bold", pad=15)
    ax.set_axis_off()

    # Grid lines (10 km spacing)
    for x in range(MAP_XLIM[0], MAP_XLIM[1] + 1, 10_000):
        ax.axvline(x, color="#CCCCCC", linewidth=0.3, zorder=0)
    for y in range(MAP_YLIM[0], MAP_YLIM[1] + 1, 10_000):
        ax.axhline(y, color="#CCCCCC", linewidth=0.3, zorder=0)

    # Scale bar (10 km) -- positioned at FOOTER_SCALE_Y, left-aligned
    bar_x = MAP_XLIM[0] + 2_000
    bar_y = FOOTER_SCALE_Y
    serif = 800
    for lw, color in [(5, "white"), (2, "black")]:
        ax.plot([bar_x, bar_x, bar_x, bar_x + 10_000, bar_x + 10_000, bar_x + 10_000],
                [bar_y + serif, bar_y - serif, bar_y, bar_y, bar_y - serif, bar_y + serif],
                color=color, linewidth=lw, solid_capstyle="butt", solid_joinstyle="miter",
                zorder=50)
    ax.text(bar_x + 5_000, bar_y + 1_500, "10 km", ha="center", va="bottom",
            fontsize=11, fontweight="bold", zorder=50,
            path_effects=[pe.withStroke(linewidth=3, foreground="white")])

    return fig, ax, sno_clipped


def place_legend(ax, handles, ncol=5, fontsize=14):
    """Place the legend at the fixed FOOTER_LEGEND_Y position, centered."""
    # Convert data Y to axes fraction for bbox_to_anchor
    y_range = MAP_YLIM[1] - MAP_YLIM[0]
    legend_frac_y = (FOOTER_LEGEND_Y - MAP_YLIM[0]) / y_range
    leg = ax.legend(
        handles=handles,
        bbox_to_anchor=(0.5, legend_frac_y),
        loc="upper center",
        fontsize=fontsize,
        ncol=ncol,
        frameon=True,
        fancybox=True,
        framealpha=0.95,
        edgecolor="#999999",
        title="Legend",
        title_fontsize=fontsize,
        columnspacing=1.0,
        handlelength=1.5,
        handletextpad=0.4,
        labelspacing=0.3,
        borderpad=0.6,
    )
    leg.set_zorder(50)
    return leg


def place_attribution(ax, text=""):
    """Place attribution text at the fixed FOOTER_ATTR_Y position, centered."""
    mid_x = (MAP_XLIM[0] + MAP_XLIM[1]) / 2
    ax.text(mid_x, FOOTER_ATTR_Y, text,
            fontsize=9, color="#666666", ha="center", va="top", zorder=50)


def save_map(fig, path):
    plt.tight_layout()
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    print(f"  Saved → {path}")

    # Also save SVG version
    svg_path = path.rsplit(".", 1)[0] + ".svg"
    fig.savefig(svg_path, format="svg", bbox_inches="tight", facecolor="white")
    svg_size_mb = os.path.getsize(svg_path) / (1024 * 1024)
    print(f"  Saved → {svg_path} ({svg_size_mb:.1f} MB)")

    # If SVG is unreasonably large (>50MB), warn and remove
    if svg_size_mb > 50:
        os.remove(svg_path)
        print(f"  WARNING: SVG too large ({svg_size_mb:.1f} MB), removed.")

    plt.close(fig)

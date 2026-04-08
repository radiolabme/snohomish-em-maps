#!/usr/bin/env python3
"""
Generate a clean map of Washington State counties with Snohomish County highlighted.
Uses US Census Bureau TIGER/Line shapefiles (OGC/OpenGIS-compliant) for county
boundaries, and Natural Earth 10m physical data for coastline and lake clipping.
"""

import os
import tempfile
import urllib.request

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
from matplotlib.patches import Patch
from shapely.ops import unary_union

TIGER_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2023/COUNTY/tl_2023_us_county.zip"
)
NE_LAND_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip"
NE_LAKES_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_lakes.zip"

WA_FIPS = "53"
EXPECTED_COUNTIES = 39
TARGET_CRS = "EPSG:2855"  # NAD83(HARN) / Washington North (meters)

WATER_COLOR = "#B3D4F0"       # soft blue for salt water / ocean
LAKE_COLOR = "#C4DEF3"        # slightly lighter blue for freshwater lakes
LAND_BG = "#F5F5F2"           # off-white land surrounding WA (neighbor states)

# The 39 official Washington State counties
WA_COUNTY_NAMES = sorted([
    "Adams", "Asotin", "Benton", "Chelan", "Clallam", "Clark", "Columbia",
    "Cowlitz", "Douglas", "Ferry", "Franklin", "Garfield", "Grant",
    "Grays Harbor", "Island", "Jefferson", "King", "Kitsap", "Kittitas",
    "Klickitat", "Lewis", "Lincoln", "Mason", "Okanogan", "Pacific", "Pend Oreille",
    "Pierce", "San Juan", "Skagit", "Skamania", "Snohomish", "Spokane",
    "Stevens", "Thurston", "Wahkiakum", "Walla Walla", "Whatcom", "Whitman", "Yakima",
])


def _fetch_cached(url: str, name: str) -> str:
    """Download a file to tmp if not already cached. Return local path."""
    local = os.path.join(tempfile.gettempdir(), name)
    if not os.path.exists(local):
        print(f"  Downloading {name}...")
        urllib.request.urlretrieve(url, local)
    return local


def load_wa_counties() -> gpd.GeoDataFrame:
    """Download (or use cached) TIGER/Line shapefile and return WA counties."""
    local_zip = _fetch_cached(TIGER_URL, "tl_2023_us_county.zip")
    print("Loading county boundaries from Census TIGER/Line...")
    gdf = gpd.read_file(f"zip://{local_zip}")
    wa = gdf[gdf["STATEFP"] == WA_FIPS].copy()
    wa = wa.to_crs(TARGET_CRS)
    print(f"  → {len(wa)} counties loaded")
    return wa


# Bounding box for PNW region in WGS84 — filter before reprojecting
# to avoid distortion of distant continents in the state-plane CRS.
_PNW_BBOX_WGS84 = (-130, 44, -116, 50)  # (lon_min, lat_min, lon_max, lat_max)


def _load_and_clip_wgs84(zip_path: str, label: str) -> gpd.GeoDataFrame:
    """Load a shapefile, clip to PNW region in WGS84, then reproject.

    Clipping continent-scale polygons in their native CRS BEFORE reprojecting
    avoids massive distortion artifacts in the state-plane projection.
    """
    from shapely.geometry import box
    from shapely.validation import make_valid

    print(f"Loading {label}...")
    gdf = gpd.read_file(f"zip://{zip_path}", bbox=_PNW_BBOX_WGS84)

    # Clip to PNW bbox while still in WGS84
    pnw_box = box(*_PNW_BBOX_WGS84)
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.apply(
        lambda g: make_valid(make_valid(g).intersection(pnw_box))
    )
    gdf = gdf[~gdf.geometry.is_empty]

    gdf = gdf.to_crs(TARGET_CRS)
    return gdf


def load_land() -> gpd.GeoDataFrame:
    """Load Natural Earth 10m land polygons, clipped to PNW."""
    local_zip = _fetch_cached(NE_LAND_URL, "ne_10m_land.zip")
    return _load_and_clip_wgs84(local_zip, "Natural Earth 10m land polygons")


def load_lakes() -> gpd.GeoDataFrame:
    """Load Natural Earth 10m lake polygons, clipped to PNW."""
    local_zip = _fetch_cached(NE_LAKES_URL, "ne_10m_lakes.zip")
    return _load_and_clip_wgs84(local_zip, "Natural Earth 10m lake polygons")


def _safe_land_union(land: gpd.GeoDataFrame, bbox) -> "shapely.Geometry":
    """Build a clean, validated land union polygon within bbox."""
    from shapely.validation import make_valid
    from shapely import extract_unique_points

    land = land.copy()
    land["geometry"] = land.geometry.apply(lambda g: make_valid(g).buffer(0))

    # Spatial filter + intersection with bbox
    mask = land.intersects(bbox)
    land_local = land[mask].copy()
    land_local["geometry"] = land_local.geometry.apply(
        lambda g: make_valid(g.intersection(bbox)).buffer(0)
    )
    land_local = land_local[~land_local.geometry.is_empty]

    return make_valid(unary_union(land_local.geometry)).buffer(0)


def clip_counties_to_land(wa: gpd.GeoDataFrame, land: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Clip county polygons to land, removing water areas (Puget Sound, ocean, straits)."""
    from shapely.geometry import box, MultiPolygon, Polygon, GeometryCollection
    from shapely.validation import make_valid

    bounds = wa.total_bounds
    pad = 50_000
    bbox = box(bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)

    land_union = _safe_land_union(land, bbox)
    # Tiny outward buffer (100m) to prevent edge-precision mismatches between
    # TIGER county boundaries and Natural Earth coastline causing inland
    # counties to be erased at shared borders.
    land_union_buffered = land_union.buffer(100)

    wa_clipped = wa.copy()
    wa_clipped["geometry"] = wa_clipped.geometry.apply(lambda g: make_valid(g).buffer(0))

    def _clip_to_polygons(geom):
        """Intersect and keep only polygon parts (discard stray lines/points)."""
        result = make_valid(geom.intersection(land_union_buffered))
        if result.is_empty:
            return result
        # Extract only Polygon/MultiPolygon parts from potential GeometryCollection
        if isinstance(result, (Polygon, MultiPolygon)):
            return result
        polys = [g for g in result.geoms if isinstance(g, (Polygon, MultiPolygon))]
        if not polys:
            return Polygon()  # empty
        return make_valid(unary_union(polys))

    wa_clipped["geometry"] = wa_clipped.geometry.apply(_clip_to_polygons)
    wa_clipped = wa_clipped[~wa_clipped.geometry.is_empty]
    print(f"  → {len(wa_clipped)} counties after land clipping")
    return wa_clipped


def clip_lakes_to_bounds(lakes: gpd.GeoDataFrame, wa: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return only lakes that intersect the map extent."""
    from shapely.geometry import box
    from shapely.validation import make_valid

    bounds = wa.total_bounds
    pad = 20_000
    bbox = box(bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)

    lakes = lakes.copy()
    lakes["geometry"] = lakes.geometry.apply(lambda g: make_valid(g).buffer(0))
    mask = lakes.intersects(bbox)
    result = lakes[mask].copy()
    result["geometry"] = result.geometry.apply(
        lambda g: make_valid(g.intersection(bbox)).buffer(0)
    )
    return result[~result.geometry.is_empty]


def render_map(
    wa: gpd.GeoDataFrame,
    out_path: str,
    land: gpd.GeoDataFrame | None = None,
    lakes: gpd.GeoDataFrame | None = None,
) -> matplotlib.figure.Figure:
    """Render the WA counties map and save to out_path. Returns the Figure."""
    matplotlib.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 14,
    })

    # If we have land data, clip counties to coastline
    if land is not None:
        wa_draw = clip_counties_to_land(wa, land)
    else:
        wa_draw = wa

    # Clip lakes to map extent
    lakes_local = None
    if lakes is not None:
        lakes_local = clip_lakes_to_bounds(lakes, wa)

    # Larger figure for better geographic detail
    fig, ax = plt.subplots(1, 1, figsize=(22, 15), facecolor="white")

    # Water background — the entire axes area is water-colored,
    # then land/counties are drawn on top. Anywhere counties were clipped
    # away (Puget Sound, straits, ocean) the water shows through.
    ax.set_facecolor(WATER_COLOR)

    # Draw surrounding land (neighbor states / Canada) as neutral background
    if land is not None:
        bounds = wa.total_bounds
        pad = 30_000
        from shapely.geometry import box
        bbox = box(bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)
        land_union = _safe_land_union(land, bbox)
        land_bg = gpd.GeoDataFrame(geometry=[land_union], crs=TARGET_CRS)
        land_bg.plot(ax=ax, color=LAND_BG, edgecolor="none")

    # Base counties (clipped to land)
    wa_draw.plot(ax=ax, color="#E8E8E8", edgecolor="#444444", linewidth=0.7)

    # Highlight Snohomish
    snohomish = wa_draw[wa_draw["NAME"].str.upper() == "SNOHOMISH"]
    snohomish.plot(ax=ax, color="#3B82F6", edgecolor="#1E3A5F", linewidth=1.2)

    # Lakes overlay
    if lakes_local is not None and len(lakes_local) > 0:
        lakes_local.plot(ax=ax, color=LAKE_COLOR, edgecolor="#8FAEC0", linewidth=0.4)

    # Labels — use the *original* (unclipped) county centroids for positioning,
    # since clipped geometries for island counties may shift the centroid oddly
    text_effects = [pe.withStroke(linewidth=3, foreground="white")]
    for _, row in wa.iterrows():
        centroid = row.geometry.representative_point()
        name = row["NAME"]
        is_snohomish = name.upper() == "SNOHOMISH"

        # For Snohomish on blue, use a dark-on-blue stroke instead of white
        if is_snohomish:
            effects = [pe.withStroke(linewidth=3, foreground="#2563EB")]
        else:
            effects = text_effects

        ax.annotate(
            name,
            xy=(centroid.x, centroid.y),
            ha="center",
            va="center",
            fontsize=14,
            fontfamily="sans-serif",
            fontweight="bold" if is_snohomish else "regular",
            color="white" if is_snohomish else "#222222",
            path_effects=effects,
        )

    # Zoom to WA with some padding
    bounds = wa.total_bounds
    x_pad = (bounds[2] - bounds[0]) * 0.04
    y_pad = (bounds[3] - bounds[1]) * 0.06
    ax.set_xlim(bounds[0] - x_pad, bounds[2] + x_pad)
    ax.set_ylim(bounds[1] - y_pad, bounds[3] + y_pad)

    # Legend & title
    legend_elements = [
        Patch(facecolor="#3B82F6", edgecolor="#1E3A5F", label="Snohomish County"),
        Patch(facecolor="#E8E8E8", edgecolor="#444444", label="Other Counties"),
        Patch(facecolor=WATER_COLOR, edgecolor="#8FAEC0", label="Water"),
    ]
    ax.legend(handles=legend_elements, loc="lower left", fontsize=14, framealpha=0.95)
    ax.set_title("Washington State Counties", fontsize=22, fontweight="bold", pad=15)
    ax.set_axis_off()
    plt.tight_layout()

    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    print(f"Map saved → {out_path}")
    return fig


def main():
    wa = load_wa_counties()
    land = load_land()
    lakes = load_lakes()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "washington_counties.png")
    fig = render_map(wa, out, land, lakes)
    plt.close(fig)


if __name__ == "__main__":
    main()

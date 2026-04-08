"""
Snohomish County — River Systems & Water Access Map
Layers: NHD flowlines (rivers/streams), NHD waterbodies (lakes/reservoirs),
FEMA flood zones (floodplain underlay), boat ramps, bridge crossings,
WSDOT roads, city labels.  Designed for swift water rescue operations.
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geopandas as gpd
import matplotlib.patheffects as pe
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.ops import unary_union
from shapely.validation import make_valid

from shapely.errors import GEOSException

from snohomish_base import (
    TARGET_CRS,
    NHD_URL,
    NHD_FLOWLINES_LAYER,
    NHD_WATERBODIES_LAYER,
    FEMA_NFHL_URL,
    FEMA_FLOOD_LAYER,
    WSDOT_ROUTES_URL,
    SNOCO_DISTRICTS_URL,
    SNOCO_CITIES_LAYER,
    HIGH_RISK_COLOR,
    MODERATE_RISK_COLOR,
    OVERPASS_BBOX,
    HIGH_RISK_ZONES,
    TEXT_HALO,
    load_snohomish_boundary,
    load_land_clipped,
    get_snohomish_bbox_wgs84,
    query_arcgis_rest,
    fetch_hillshade,
    create_base_map,
    place_legend,
    place_attribution,
    save_map,
    query_overpass,
    overpass_to_points_gdf,
    clip_to_county,
    clip_lines_to_county,
)

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_rivers.png")

BBOX = OVERPASS_BBOX

# Major rivers for special styling and labeling
MAJOR_RIVERS = {
    "Snohomish River", "Skykomish River", "Stillaguamish River",
    "Pilchuck River", "Sauk River", "Snoqualmie River",
    "North Fork Stillaguamish River", "South Fork Stillaguamish River",
    "North Fork Skykomish River", "South Fork Skykomish River",
    "Sultan River", "Wallace River", "Woods Creek",
    "South Fork Snoqualmie River",
}




def fetch_nhd_flowlines(bbox):
    """Fetch NHD flowlines (rivers/streams) with pagination."""
    print(f"Fetching NHD Flowlines (layer {NHD_FLOWLINES_LAYER})...")
    try:
        flowlines = query_arcgis_rest(
            NHD_URL, NHD_FLOWLINES_LAYER,
            bbox_wgs84=bbox,
            out_fields="gnis_name,ftype,fcode,lengthkm",
        )
        if flowlines.empty:
            print("  WARNING: No flowline data returned.")
            return flowlines
        print(f"  Total flowline features: {len(flowlines)}")

        # Filter: keep named streams and larger unnamed ones (ftype 460 = Stream/River)
        has_name = flowlines["gnis_name"].notna() & (flowlines["gnis_name"] != "")
        is_stream = flowlines["ftype"].isin([460])
        is_artificial = flowlines["ftype"].isin([558])  # artificial path (often river routes)

        # Keep: named features, or streams > 0.5 km, or artificial paths > 1 km
        long_unnamed = (~has_name) & is_stream & (flowlines["lengthkm"] > 0.5)
        long_artificial = is_artificial & has_name

        flowlines_filtered = flowlines[has_name | long_unnamed | long_artificial].copy()
        print(f"  After filtering: {len(flowlines_filtered)} flowlines")
        return flowlines_filtered

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch NHD flowlines: {e}")
        return gpd.GeoDataFrame()


def fetch_nhd_waterbodies(bbox):
    """Fetch NHD waterbodies (lakes, reservoirs)."""
    print(f"Fetching NHD Waterbodies (layer {NHD_WATERBODIES_LAYER})...")
    try:
        waterbodies = query_arcgis_rest(
            NHD_URL, NHD_WATERBODIES_LAYER,
            bbox_wgs84=bbox,
            out_fields="gnis_name,ftype,areasqkm",
        )
        if waterbodies.empty:
            print("  WARNING: No waterbody data returned.")
            return waterbodies
        print(f"  Total waterbody features: {len(waterbodies)}")
        return waterbodies
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch NHD waterbodies: {e}")
        return gpd.GeoDataFrame()


def fetch_flood_zones(bbox):
    """Fetch FEMA flood zones for floodplain underlay."""
    print("Fetching FEMA flood zones...")
    try:
        flood = query_arcgis_rest(
            FEMA_NFHL_URL, FEMA_FLOOD_LAYER,
            bbox_wgs84=bbox,
            out_fields="FLD_ZONE,ZONE_SUBTY",
        )
        if flood.empty:
            print("  WARNING: No flood zone data returned.")
            return flood
        print(f"  Total flood zone features: {len(flood)}")
        return flood
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch FEMA flood zones: {e}")
        return gpd.GeoDataFrame()


def fetch_boat_ramps(county_geom):
    """Fetch boat ramps/launches from OpenStreetMap."""
    print("Fetching boat ramps from Overpass...")
    bbox_str = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    query = (
        f'[out:json];('
        f'node["leisure"="slipway"]({bbox_str});'
        f'node["amenity"="boat_rental"]({bbox_str});'
        f'way["leisure"="slipway"]({bbox_str});'
        f');out center;'
    )
    result = query_overpass(query)
    gdf = overpass_to_points_gdf(result, county_geom)
    print(f"  Found {len(gdf)} boat ramps/launches in county")
    return gdf


def fetch_bridges(county_geom):
    """Fetch bridge crossings from OpenStreetMap."""
    print("Fetching bridge crossings from Overpass...")
    bbox_str = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"
    query = (
        f'[out:json];'
        f'way["bridge"="yes"]["highway"]({bbox_str});'
        f'out center;'
    )
    result = query_overpass(query)
    gdf = overpass_to_points_gdf(result, county_geom)
    print(f"  Found {len(gdf)} bridge crossings in county")
    return gdf


def fetch_roads(bbox, sno):
    """Fetch WSDOT state routes for context."""
    print("Fetching WSDOT state routes...")
    try:
        roads = query_arcgis_rest(
            WSDOT_ROUTES_URL, 0,
            bbox_wgs84=bbox,
            where="RT_TYPEA IN ('IS','US','SR') AND RelRouteType=''",
            out_fields="DISPLAY,RT_TYPEA,StateRouteNumber",
        )
        if roads.empty:
            print("  WARNING: No road data returned.")
            return roads
        print(f"  Total road features: {len(roads)}")
        roads_clipped = clip_lines_to_county(roads, sno)
        print(f"  After clipping: {len(roads_clipped)}")
        return roads_clipped
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch roads: {e}")
        return gpd.GeoDataFrame()


def fetch_cities():
    """Fetch city boundaries from SnoCoWA layer 13."""
    print("Fetching city boundaries...")
    try:
        cities = query_arcgis_rest(
            SNOCO_DISTRICTS_URL, SNOCO_CITIES_LAYER,
            out_fields="NAME,FULL_NAME",
        )
        if cities.empty:
            print("  WARNING: No city data returned.")
        else:
            print(f"  Total city features: {len(cities)}")
        return cities
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch cities: {e}")
        return gpd.GeoDataFrame()

def render_flood_underlay(ax, flood, sno):
    """Render FEMA flood zones as a very light underlay."""
    if flood.empty:
        return
    print("Rendering flood zone underlay...")

    flood["risk"] = flood.apply(
        lambda row: "high" if str(row.get("FLD_ZONE", "")).strip().upper() in HIGH_RISK_ZONES
        else "moderate" if ("0.2" in str(row.get("ZONE_SUBTY", "")))
        else "minimal",
        axis=1,
    )
    flood_clipped = clip_to_county(flood, sno)
    high = flood_clipped[flood_clipped["risk"] == "high"]
    mod = flood_clipped[flood_clipped["risk"] == "moderate"]

    if not high.empty:
        high.plot(ax=ax, color=HIGH_RISK_COLOR, edgecolor="none", alpha=0.15, zorder=2)
        print(f"  High risk flood zones: {len(high)} features")
    if not mod.empty:
        mod.plot(ax=ax, color=MODERATE_RISK_COLOR, edgecolor="none", alpha=0.10, zorder=2)
        print(f"  Moderate risk flood zones: {len(mod)} features")


def render_waterbodies(ax, waterbodies, sno):
    """Render NHD waterbodies (lakes, reservoirs)."""
    if waterbodies.empty:
        return
    print("Rendering waterbodies...")
    wb_clipped = clip_to_county(waterbodies, sno)
    if wb_clipped.empty:
        return
    wb_clipped.plot(ax=ax, color="#A8D4F0", edgecolor="#4A90C4", linewidth=0.4,
                    alpha=0.8, zorder=4)
    print(f"  Rendered {len(wb_clipped)} waterbodies")

    # Label named waterbodies that are large enough
    name_col = "gnis_name"
    if name_col in wb_clipped.columns:
        for _, row in wb_clipped.iterrows():
            name = row.get(name_col, "")
            area = row.get("areasqkm", 0)
            if not name or str(name).strip() == "" or str(name) == "None":
                continue
            if area is not None and float(area) < 0.3:
                continue
            pt = row.geometry.representative_point()
            ax.text(
                pt.x, pt.y, str(name),
                fontsize=7, fontstyle="italic",
                ha="center", va="center",
                color="#1A5276",
                path_effects=TEXT_HALO,
                zorder=18,
            )


def render_flowlines(ax, flowlines, sno):
    """Render NHD flowlines with styling by river importance."""
    if flowlines.empty:
        return
    print("Rendering flowlines...")
    fl_clipped = clip_lines_to_county(flowlines, sno)
    if fl_clipped.empty:
        return

    # Classify rivers
    name_col = "gnis_name"
    has_name = fl_clipped[name_col].notna() & (fl_clipped[name_col] != "") & (fl_clipped[name_col] != "None")

    # Major named rivers
    is_major = has_name & fl_clipped[name_col].isin(MAJOR_RIVERS)
    major = fl_clipped[is_major]

    # Other named streams
    is_named_minor = has_name & ~is_major
    named_minor = fl_clipped[is_named_minor]

    # Unnamed streams
    unnamed = fl_clipped[~has_name]

    # Draw unnamed first (bottom)
    if not unnamed.empty:
        unnamed.plot(ax=ax, color="#9DC3E6", linewidth=0.4, alpha=0.5, zorder=5)
        print(f"  Unnamed streams: {len(unnamed)}")

    # Named minor streams
    if not named_minor.empty:
        named_minor.plot(ax=ax, color="#4A90C4", linewidth=1.2, alpha=0.8, zorder=6)
        print(f"  Named minor streams: {len(named_minor)}")

    # Major rivers (thick, prominent)
    if not major.empty:
        # Draw a white outline for emphasis
        major.plot(ax=ax, color="white", linewidth=3.5, alpha=0.6, zorder=6.5)
        major.plot(ax=ax, color="#1A5AAF", linewidth=2.8, alpha=0.9, zorder=7)
        print(f"  Major rivers: {len(major)}")

    return fl_clipped


def label_major_rivers(ax, flowlines):
    """Label major rivers along their course using rotated text."""
    if flowlines.empty:
        return
    print("Labeling major rivers...")

    name_col = "gnis_name"
    has_name = flowlines[name_col].notna() & (flowlines[name_col] != "") & (flowlines[name_col] != "None")
    major = flowlines[has_name & flowlines[name_col].isin(MAJOR_RIVERS)]

    if major.empty:
        return

    labeled = set()
    for river_name in MAJOR_RIVERS:
        subset = major[major[name_col] == river_name]
        if subset.empty:
            continue
        if river_name in labeled:
            continue

        # Get the longest segment for placement
        lengths = subset.geometry.length
        if lengths.empty:
            continue
        longest_idx = lengths.idxmax()
        geom = subset.loc[longest_idx, "geometry"]

        if geom.is_empty:
            continue

        # Get point at 40% along the longest segment for label placement
        try:
            mid = geom.interpolate(0.4, normalized=True)
            # Get angle from nearby points for rotation
            p1 = geom.interpolate(0.35, normalized=True)
            p2 = geom.interpolate(0.45, normalized=True)
            angle_rad = np.arctan2(p2.y - p1.y, p2.x - p1.x)
            angle_deg = np.degrees(angle_rad)

            # Keep text readable (not upside down)
            if angle_deg > 90:
                angle_deg -= 180
            elif angle_deg < -90:
                angle_deg += 180

        except (GEOSException, ValueError, TypeError):
            mid = geom.centroid
            angle_deg = 0

        # Shorten display name
        display_name = river_name.replace(" River", " R.").replace(" Creek", " Cr.")
        display_name = display_name.replace("North Fork ", "N.F. ").replace("South Fork ", "S.F. ")

        ax.text(
            mid.x, mid.y, display_name,
            fontsize=9, fontweight="bold", fontstyle="italic",
            ha="center", va="center",
            rotation=angle_deg, rotation_mode="anchor",
            color="#0A3A7A",
            path_effects=[pe.withStroke(linewidth=4, foreground="white", alpha=0.9)],
            zorder=19,
        )
        labeled.add(river_name)

    print(f"  Labeled {len(labeled)} rivers")


def render_roads(ax, roads):
    """Render roads as thin gray context lines."""
    if roads.empty:
        return
    print("Rendering roads...")
    # All roads as thin gray
    roads.plot(ax=ax, color="#999999", linewidth=0.6, alpha=0.5, zorder=3)

    # Slightly thicker for interstates/US highways
    for rt_type, lw, color in [("IS", 1.2, "#777777"), ("US", 0.9, "#888888")]:
        if "RT_TYPEA" in roads.columns:
            subset = roads[roads["RT_TYPEA"] == rt_type]
            if not subset.empty:
                subset.plot(ax=ax, color=color, linewidth=lw, alpha=0.5, zorder=3)


def render_cities(ax, cities):
    """Render city labels for orientation."""
    if cities.empty:
        return
    print("Rendering city labels...")

    name_col = "NAME"
    if name_col not in cities.columns:
        for c in ["FULL_NAME", "name", "Name"]:
            if c in cities.columns:
                name_col = c
                break

    # Thin outline
    cities.plot(ax=ax, facecolor="none", edgecolor="#888888", linewidth=0.4,
                alpha=0.4, zorder=3)

    # Label cities
    for _, row in cities.iterrows():
        geom = row.geometry
        if geom.is_empty:
            continue
        name = str(row.get(name_col, "")).strip()
        if not name:
            continue

        pt = geom.representative_point()
        ax.text(
            pt.x, pt.y, name,
            fontsize=8, fontweight="bold",
            ha="center", va="center",
            color="#555555", alpha=0.7,
            path_effects=TEXT_HALO,
            zorder=16,
        )


def render_boat_ramps(ax, ramps):
    """Render boat ramps as green triangle markers."""
    if ramps.empty:
        return
    print(f"Rendering {len(ramps)} boat ramps...")
    ax.scatter(
        ramps.geometry.x, ramps.geometry.y,
        marker="^", s=60, color="#2E7D32",
        edgecolor="white", linewidth=0.5,
        zorder=14,
    )
    # Label named ramps
    for _, row in ramps.iterrows():
        name = row.get("name", "")
        if not name or str(name).strip() == "":
            continue
        ax.annotate(
            str(name),
            xy=(row.geometry.x, row.geometry.y),
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=6, fontweight="bold",
            color="#1B5E20",
            path_effects=TEXT_HALO,
            zorder=17,
        )


def render_bridges(ax, bridges):
    """Render bridge crossings as small black diamond markers."""
    if bridges.empty:
        return
    print(f"Rendering {len(bridges)} bridge crossings...")
    ax.scatter(
        bridges.geometry.x, bridges.geometry.y,
        marker="D", s=12, color="#333333",
        edgecolor="white", linewidth=0.3,
        alpha=0.7, zorder=13,
    )


def main():
    print("=" * 60)
    print("Snohomish County — River Systems & Water Access")
    print("=" * 60)

    print("\nLoading county boundary...")
    sno = load_snohomish_boundary()
    land = load_land_clipped()
    bbox = get_snohomish_bbox_wgs84()
    county_geom = make_valid(unary_union(sno.geometry)).buffer(0)

    # Fetch all data
    flowlines = fetch_nhd_flowlines(bbox)
    waterbodies = fetch_nhd_waterbodies(bbox)
    flood = fetch_flood_zones(bbox)

    print("\n--- OpenStreetMap Data ---")
    boat_ramps = fetch_boat_ramps(county_geom)
    time.sleep(2)  # Be polite to Overpass API
    bridges = fetch_bridges(county_geom)

    print("\n--- Context Layers ---")
    roads = fetch_roads(bbox, sno)
    cities = fetch_cities()

    # Render
    print("\nFetching hillshade...")
    hill_img, hill_extent = fetch_hillshade(bbox)

    print("Creating base map...")
    fig, ax, sno_clipped = create_base_map(
        sno, land,
        title="Snohomish County \u2014 River Systems & Water Access",
    )

    # Hillshade background
    ax.imshow(hill_img, extent=hill_extent, zorder=1, alpha=0.3,
              interpolation="bilinear")

    # Re-draw county on top of hillshade
    sno_clipped.plot(ax=ax, color="none", edgecolor="#444444", linewidth=1.2, zorder=1.5)

    # Layers in z-order
    render_flood_underlay(ax, flood, sno)     # z=2
    render_roads(ax, roads)                    # z=3
    render_cities(ax, cities)                  # z=3-16
    render_waterbodies(ax, waterbodies, sno)   # z=4
    fl_clipped = render_flowlines(ax, flowlines, sno)  # z=5-7
    render_bridges(ax, bridges)                # z=13
    render_boat_ramps(ax, boat_ramps)          # z=14-17
    if fl_clipped is not None:
        label_major_rivers(ax, fl_clipped)     # z=19

    # Re-draw county border on top of everything
    sno_clipped.plot(ax=ax, color="none", edgecolor="#444444", linewidth=1.2, zorder=20)

    # Legend
    legend_handles = [
        Line2D([0], [0], color="#1A5AAF", linewidth=3.0, label="Major Rivers"),
        Line2D([0], [0], color="#4A90C4", linewidth=1.5, label="Named Streams"),
        Line2D([0], [0], color="#9DC3E6", linewidth=0.8, alpha=0.6, label="Minor Streams"),
        Patch(facecolor="#A8D4F0", edgecolor="#4A90C4", linewidth=0.5,
              label="Lakes / Reservoirs"),
        Patch(facecolor=HIGH_RISK_COLOR, edgecolor="none", alpha=0.15,
              label="FEMA Floodplain (High Risk)"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#2E7D32",
               markeredgecolor="white", markersize=10, label="Boat Ramps"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor="#333333",
               markeredgecolor="white", markersize=6, label="Bridge Crossings"),
    ]

    place_legend(ax, legend_handles, ncol=4, fontsize=11)
    place_attribution(ax, "Data: USGS NHD, OpenStreetMap contributors, FEMA NFHL, WSDOT")

    # Save
    print("\nSaving map...")
    save_map(fig, OUTPUT)

    # Summary
    print("\nLayer summary:")
    print(f"  Flowlines: {len(flowlines) if not flowlines.empty else 0}")
    print(f"  Waterbodies: {len(waterbodies) if not waterbodies.empty else 0}")
    print(f"  Flood zones: {len(flood) if not flood.empty else 0}")
    print(f"  Boat ramps: {len(boat_ramps)}")
    print(f"  Bridge crossings: {len(bridges)}")
    print(f"  Road segments: {len(roads) if not roads.empty else 0}")
    print(f"  Cities: {len(cities) if not cities.empty else 0}")
    print("Done!")


if __name__ == "__main__":
    main()

"""
Snohomish County -- Terrain, Trails & SAR Access Map
Layers: hillshade (prominent), trails from OSM, national forest boundary,
state parks, major rivers (NHD), roads, cities.
"""

import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geopandas as gpd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import LineString
from shapely.ops import unary_union
from shapely.validation import make_valid

from shapely.errors import GEOSException

from snohomish_base import (
    TARGET_CRS,
    SNOCO_DISTRICTS_URL,
    SNOCO_CITIES_LAYER,
    SNOCO_FOREST_LAYER,
    NHD_FLOWLINES_LAYER,
    WSDOT_ROUTES_URL,
    WA_STATE_PARKS_URL,
    NHD_URL,
    STATE_PARK_COLOR,
    TEXT_HALO,
    TEXT_HALO_BOLD,
    load_snohomish_boundary,
    load_land_clipped,
    get_snohomish_bbox_wgs84,
    query_arcgis_rest,
    fetch_hillshade,
    create_base_map,
    place_legend,
    place_attribution,
    save_map,
    clip_to_county,
    clip_lines_to_county,
    query_overpass,
)

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_terrain.png")



def fetch_and_render_trails(ax, sno):
    """Fetch hiking trails, footways, tracks, and hiking routes from OSM."""
    print("\n--- Trails (OpenStreetMap) ---")

    bbox_str = "47.78,-122.46,48.30,-120.91"

    # Queries for different trail types
    queries = {
        "path": f'[out:json];way["highway"="path"]({bbox_str});out geom;',
        "footway": f'[out:json];way["highway"="footway"]({bbox_str});out geom;',
        "track": f'[out:json];way["highway"="track"]({bbox_str});out geom;',
        "hiking": f'[out:json];relation["route"="hiking"]({bbox_str});out geom;',
    }

    all_hiking_lines = []  # path + footway + hiking relations
    all_track_lines = []   # tracks (forest roads)

    for trail_type, query in queries.items():
        try:
            print(f"  Querying OSM for {trail_type}...")
            result = query_overpass(query)
            elements = result.get("elements", [])
            print(f"  Got {len(elements)} {trail_type} elements")

            for element in elements:
                geom_points = element.get("geometry", [])
                if len(geom_points) < 2:
                    # For relations, extract members' geometry
                    members = element.get("members", [])
                    for member in members:
                        member_geom = member.get("geometry", [])
                        if len(member_geom) >= 2:
                            coords = [(p["lon"], p["lat"]) for p in member_geom]
                            line = LineString(coords)
                            all_hiking_lines.append(line)
                    continue

                coords = [(p["lon"], p["lat"]) for p in geom_points]
                line = LineString(coords)

                if trail_type == "track":
                    all_track_lines.append(line)
                else:
                    all_hiking_lines.append(line)

        except (GEOSException, ValueError, TypeError) as e:
            print(f"  WARNING: Failed to fetch {trail_type} trails: {e}")

    # Build GeoDataFrames and reproject
    county_union = make_valid(unary_union(sno.geometry)).buffer(0)

    if all_hiking_lines:
        hiking_gdf = gpd.GeoDataFrame(
            geometry=all_hiking_lines, crs="EPSG:4326"
        ).to_crs(TARGET_CRS)
        hiking_gdf["geometry"] = hiking_gdf.geometry.apply(
            lambda g: make_valid(g).intersection(county_union)
        )
        hiking_gdf = hiking_gdf[~hiking_gdf.geometry.is_empty]
        print(f"  Hiking trails after clip: {len(hiking_gdf)}")
        if not hiking_gdf.empty:
            hiking_gdf.plot(
                ax=ax, color="#FF6D00", linewidth=1.0,
                linestyle="-", zorder=5,
            )
    else:
        print("  No hiking trails found.")

    if all_track_lines:
        track_gdf = gpd.GeoDataFrame(
            geometry=all_track_lines, crs="EPSG:4326"
        ).to_crs(TARGET_CRS)
        track_gdf["geometry"] = track_gdf.geometry.apply(
            lambda g: make_valid(g).intersection(county_union)
        )
        track_gdf = track_gdf[~track_gdf.geometry.is_empty]
        print(f"  Forest tracks after clip: {len(track_gdf)}")
        if not track_gdf.empty:
            track_gdf.plot(
                ax=ax, color="#795548", linewidth=1.0,
                linestyle="--", zorder=5,
            )
    else:
        print("  No forest tracks found.")


def fetch_and_render_national_forest(ax, sno):
    print("\n--- National Forest Boundary ---")
    try:
        nf = query_arcgis_rest(SNOCO_DISTRICTS_URL, SNOCO_FOREST_LAYER)
        if not nf.empty:
            nf_clipped = clip_to_county(nf, sno)
            if not nf_clipped.empty:
                nf_clipped.plot(
                    ax=ax, facecolor="none",
                    edgecolor="#2D6A2E", linewidth=1.2,
                    linestyle="-", alpha=0.6, zorder=2,
                )
                print(f"  National Forest: {len(nf_clipped)} features (edge only)")
        else:
            print("  WARNING: No National Forest data returned.")
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch National Forest: {e}")

def fetch_and_render_state_parks(ax, bbox, sno):
    print("\n--- State Parks ---")
    try:
        parks = query_arcgis_rest(WA_STATE_PARKS_URL, 2, bbox_wgs84=bbox)
        if not parks.empty:
            parks_clipped = clip_to_county(parks, sno)
            if not parks_clipped.empty:
                parks_clipped = parks_clipped[parks_clipped.geometry.area > 2_000_000]
            if not parks_clipped.empty:
                parks_clipped.plot(
                    ax=ax, color=STATE_PARK_COLOR, alpha=0.4,
                    edgecolor="#2E7D32", linewidth=0.8, zorder=4,
                )
                print(f"  State Parks: {len(parks_clipped)} features")

                # Label larger parks
                name_col = None
                for c in ["LABEL", "NAME", "UnitName", "name", "Name", "PARKNAME"]:
                    if c in parks_clipped.columns:
                        name_col = c
                        break
                if name_col:
                    for _, row in parks_clipped.iterrows():
                        geom = row.geometry
                        if geom.is_empty or geom.area < 2_000_000:
                            continue
                        name = str(row.get(name_col, ""))
                        if not name.strip():
                            continue
                        pt = geom.representative_point()
                        ax.text(
                            pt.x, pt.y, name,
                            fontsize=8, ha="center", va="center",
                            fontstyle="italic", color="#1B5E20",
                            path_effects=TEXT_HALO, zorder=12,
                        )
        else:
            print("  WARNING: No State Parks data returned.")
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch State Parks: {e}")

def fetch_and_render_rivers(ax, bbox, sno):
    print("\n--- Major Rivers (NHD) ---")
    try:
        rivers = query_arcgis_rest(
            NHD_URL, NHD_FLOWLINES_LAYER,
            bbox_wgs84=bbox,
            out_fields="gnis_name,ftype,lengthkm",
        )
        if rivers.empty:
            print("  WARNING: No river data returned.")
            return

        print(f"  Total river features: {len(rivers)}")

        # Keep only named rivers
        name_col = None
        for c in ["gnis_name", "GNIS_NAME", "gnis_Name"]:
            if c in rivers.columns:
                name_col = c
                break

        if name_col:
            named_rivers = rivers[
                rivers[name_col].notna()
                & (rivers[name_col].astype(str).str.strip() != "")
            ].copy()
            print(f"  Named rivers: {len(named_rivers)}")
        else:
            named_rivers = rivers.copy()

        if named_rivers.empty:
            return

        # Clip to county
        rivers_clipped = clip_lines_to_county(named_rivers, sno)
        print(f"  After clipping: {len(rivers_clipped)}")

        if not rivers_clipped.empty:
            rivers_clipped.plot(
                ax=ax, color="#1976D2", linewidth=1.5,
                alpha=0.7, zorder=3,
            )

            # Label major rivers
            if name_col:
                labeled = set()
                for _, row in rivers_clipped.iterrows():
                    name = str(row.get(name_col, "")).strip()
                    if not name or name in labeled:
                        continue
                    # Only label longer segments
                    if row.geometry.length < 5000:
                        continue
                    labeled.add(name)
                    try:
                        mid = row.geometry.interpolate(0.5, normalized=True)
                    except (GEOSException, ValueError, TypeError):
                        mid = row.geometry.centroid
                    ax.text(
                        mid.x, mid.y, name,
                        fontsize=7, fontstyle="italic",
                        color="#0D47A1", ha="center", va="center",
                        path_effects=TEXT_HALO, zorder=12,
                    )

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch rivers: {e}")

KEY_ROUTES = {"5", "2", "9", "530", "92", "20"}


def fetch_and_render_roads(ax, bbox, sno):
    print("\n--- Roads (WSDOT) ---")
    try:
        roads = query_arcgis_rest(
            WSDOT_ROUTES_URL, 0,
            bbox_wgs84=bbox,
            where="RT_TYPEA IN ('IS','US','SR') AND RelRouteType=''",
            out_fields="DISPLAY,RT_TYPEA,StateRouteNumber",
        )
        if roads.empty:
            print("  WARNING: No road data returned.")
            return
        print(f"  Total road features: {len(roads)}")

        roads_clipped = clip_lines_to_county(roads, sno)
        print(f"  After clipping: {len(roads_clipped)}")

        if roads_clipped.empty:
            return

        # Render all roads in gray, thinner than combined map
        road_styles = {
            "SR": ("#888888", 0.8, 6),
            "US": ("#666666", 1.2, 6),
            "IS": ("#555555", 1.5, 6),
        }

        for rt_type in ["SR", "US", "IS"]:
            subset = roads_clipped[roads_clipped["RT_TYPEA"] == rt_type]
            if subset.empty:
                continue
            color, lw, zo = road_styles[rt_type]
            subset.plot(ax=ax, color=color, linewidth=lw, zorder=zo)
            print(f"  {rt_type}: {len(subset)} segments")

        # Label key routes
        labeled = set()
        for _, row in roads_clipped.iterrows():
            rt_num = str(row.get("StateRouteNumber", "")).strip()
            rt_type = str(row.get("RT_TYPEA", "")).strip()

            if rt_num not in KEY_ROUTES:
                continue
            label_key = f"{rt_type}_{rt_num}"
            if label_key in labeled:
                continue

            geom = row.geometry
            if geom.is_empty:
                continue

            try:
                mid = geom.interpolate(0.5, normalized=True)
            except (GEOSException, ValueError, TypeError):
                mid = geom.centroid

            if rt_type == "IS":
                label = f"I-{rt_num}"
            elif rt_type == "US":
                label = f"US-{rt_num}"
            else:
                label = f"SR-{rt_num}"

            ax.text(
                mid.x, mid.y, label,
                fontsize=8, fontweight="bold",
                ha="center", va="center",
                color="#333333",
                path_effects=TEXT_HALO_BOLD, zorder=12,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                          edgecolor="#AAAAAA", alpha=0.8, linewidth=0.5),
            )
            labeled.add(label_key)

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch roads: {e}")

LABEL_CITIES = {
    "Everett", "Marysville", "Lake Stevens", "Lynnwood",
    "Darrington", "Index", "Gold Bar", "Sultan", "Granite Falls",
    "Snohomish", "Monroe", "Arlington", "Stanwood",
}


def fetch_and_render_cities(ax, sno):
    print("\n--- Cities / Towns ---")
    try:
        cities = query_arcgis_rest(
            SNOCO_DISTRICTS_URL, SNOCO_CITIES_LAYER,
            out_fields="NAME,FULL_NAME",
        )
        if cities.empty:
            print("  WARNING: No city data returned.")
            return
        print(f"  Total city features: {len(cities)}")

        name_col = "NAME"
        if name_col not in cities.columns:
            for c in ["FULL_NAME", "name", "Name"]:
                if c in cities.columns:
                    name_col = c
                    break

        # Only label select cities for orientation (no boundary outlines to keep map clean)
        from adjustText import adjust_text

        city_texts = []
        city_xs = []
        city_ys = []
        for _, row in cities.iterrows():
            geom = row.geometry
            if geom.is_empty:
                continue
            name = str(row.get(name_col, "")).strip()
            if not name or name not in LABEL_CITIES:
                continue

            pt = geom.representative_point()
            city_xs.append(pt.x)
            city_ys.append(pt.y)

            t = ax.text(
                pt.x, pt.y, name,
                fontsize=9, fontweight="bold",
                ha="center", va="center",
                color="#222222",
                path_effects=TEXT_HALO_BOLD, zorder=10,
            )
            city_texts.append(t)

        if city_texts:
            adjust_text(
                city_texts,
                x=city_xs, y=city_ys,
                ax=ax,
                force_text=(0.8, 1.0),
                force_points=(0.5, 0.5),
                expand=(1.3, 1.5),
                arrowprops=dict(arrowstyle="-", color="#666666", linewidth=0.6),
            )

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch cities: {e}")

def build_legend(ax):
    handles = [
        # Trails
        Line2D([0], [0], color="#FF6D00", linewidth=1.5,
               linestyle="-", label="Hiking Trail"),
        Line2D([0], [0], color="#795548", linewidth=1.5,
               linestyle="--", label="Forest Road/Track"),
        # Rivers
        Line2D([0], [0], color="#1976D2", linewidth=1.5,
               alpha=0.7, label="Major River"),
        # Public lands
        Patch(facecolor="none", edgecolor="#2D6A2E",
              linewidth=1.2, label="National Forest"),
        Patch(facecolor=STATE_PARK_COLOR, alpha=0.4, edgecolor="#2E7D32",
              linewidth=0.8, label="State Park"),
        # Roads
        Line2D([0], [0], color="#555555", linewidth=1.5, label="Interstate"),
        Line2D([0], [0], color="#666666", linewidth=1.2, label="US Highway"),
        Line2D([0], [0], color="#888888", linewidth=0.8, label="State Route"),
    ]

    place_legend(ax, handles, ncol=4, fontsize=13)


def main():
    print("=" * 60)
    print("Snohomish County -- Terrain, Trails & SAR Access Map")
    print("=" * 60)

    # 1. Load base data
    print("\nLoading Snohomish County boundary...")
    sno = load_snohomish_boundary()

    print("Loading land polygons...")
    land = load_land_clipped()

    bbox = get_snohomish_bbox_wgs84()
    print(f"  Snohomish bbox (WGS84): {bbox}")

    # 2. Create base map -- make county fill nearly transparent so hillshade dominates
    print("\nCreating base map...")
    fig, ax, sno_clipped = create_base_map(
        sno, land=land,
        title="Snohomish County \u2014 Terrain, Trails & SAR Access",
    )

    # Override county fill to be very light so hillshade shows through
    # Redraw county with near-transparent fill
    sno_clipped.plot(
        ax=ax, color="#FFFFFF", alpha=0.05,
        edgecolor="#444444", linewidth=1.2, zorder=0.5,
    )

    # 3. z=1: Hillshade background (prominent -- this is the terrain map)
    print("\nFetching hillshade...")
    try:
        img, extent = fetch_hillshade(bbox, width=3000, height=1800)
        ax.imshow(img, extent=extent, alpha=0.7, zorder=1, aspect="auto")
        print("  Hillshade rendered (alpha=0.7).")
    except (urllib.error.URLError, OSError) as e:
        print(f"  WARNING: Failed to fetch hillshade: {e}")

    # 4. z=2: National Forest boundary (edge only)
    fetch_and_render_national_forest(ax, sno)

    # 5. z=3: Major rivers (NHD)
    fetch_and_render_rivers(ax, bbox, sno)

    # 6. z=4: State Parks
    fetch_and_render_state_parks(ax, bbox, sno)

    # 7. z=5: Trails (OSM)
    fetch_and_render_trails(ax, sno)

    # 8. z=6: Roads (gray, for access context)
    fetch_and_render_roads(ax, bbox, sno)

    # 9. z=9-10: City labels for orientation
    fetch_and_render_cities(ax, sno)

    # 10. z=11: County border redraw
    print("\nRedrawing county border on top...")
    sno.plot(ax=ax, facecolor="none", edgecolor="#222222", linewidth=1.5, zorder=11)

    # 11. Legend
    build_legend(ax)

    # 12. Attribution
    place_attribution(
        ax,
        "Data: USGS Shaded Relief, OpenStreetMap/Overpass, NHD, WSDOT, "
        "Snohomish County GIS, WA State Parks",
    )

    # 13. Save
    print(f"\nSaving map to {OUTPUT}...")
    save_map(fig, OUTPUT)
    print("Done!")


if __name__ == "__main__":
    main()

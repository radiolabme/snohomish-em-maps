"""
Snohomish County — Combined Hazard & Infrastructure Map
Layers: hillshade, FEMA flood zones, volcanic/lahar hazards,
water management district outlines, public lands, roads, cities, county border.
"""

import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from shapely.errors import GEOSException
from shapely.ops import unary_union
from shapely.validation import make_valid

from snohomish_base import (
    FEMA_NFHL_URL,
    FEMA_FLOOD_LAYER,
    VOLCANIC_URL,
    VOLCANIC_LAYER,
    SNOCO_DISTRICTS_URL,
    SNOCO_CITIES_LAYER,
    SNOCO_FOREST_LAYER,
    SNOCO_DIKING_LAYER,
    SNOCO_DRAINAGE_LAYER,
    SNOCO_FLOOD_CTRL_LAYER,
    WSDOT_ROUTES_URL,
    WA_STATE_PARKS_URL,
    HIGH_RISK_COLOR,
    MODERATE_RISK_COLOR,
    LAHAR_COLOR,
    NEAR_VOLCANO_COLOR,
    TEPHRA_COLOR,
    NATIONAL_FOREST_COLOR,
    STATE_PARK_COLOR,
    INTERSTATE_COLOR,
    US_HIGHWAY_COLOR,
    STATE_ROUTE_COLOR,
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
    classify_flood_risk,
    find_name_column,
)

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_combined.png")

NPS_LANDS_URL = (
    "https://services1.arcgis.com/fBc8EJBxQRMcHlei/arcgis/rest/services/"
    "NPS_Land_Resources_Division_Boundary_and_Tract_Data_Service/FeatureServer"
)


def fetch_and_render_flood(ax, bbox, sno):
    print("\n--- FEMA Flood Zones ---")
    try:
        flood = query_arcgis_rest(
            FEMA_NFHL_URL, FEMA_FLOOD_LAYER, bbox_wgs84=bbox,
            out_fields="FLD_ZONE,ZONE_SUBTY",
        )
        if flood.empty:
            print("  WARNING: No flood zone data returned.")
            return
        print(f"  Total features: {len(flood)}")

        flood["risk"] = flood.apply(classify_flood_risk, axis=1)
        flood_clipped = clip_to_county(flood, sno)
        print(f"  After clipping: {len(flood_clipped)}")

        # High risk
        high = flood_clipped[flood_clipped["risk"] == "high"]
        if not high.empty:
            high.plot(ax=ax, color=HIGH_RISK_COLOR, edgecolor="none", alpha=0.45, zorder=2)
            print(f"  High risk: {len(high)} features")

        # Moderate risk
        mod = flood_clipped[flood_clipped["risk"] == "moderate"]
        if not mod.empty:
            mod.plot(ax=ax, color=MODERATE_RISK_COLOR, edgecolor="none", alpha=0.45, zorder=2)
            print(f"  Moderate risk: {len(mod)} features")

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch flood zones: {e}")

def fetch_and_render_volcanic(ax, bbox, sno):
    print("\n--- Volcanic / Lahar Hazards ---")
    try:
        volc = query_arcgis_rest(VOLCANIC_URL, VOLCANIC_LAYER, bbox_wgs84=bbox, out_fields="*")
        if volc.empty:
            print("  WARNING: No volcanic hazard data returned.")
            return
        print(f"  Total features: {len(volc)}")

        volc_clipped = clip_to_county(volc, sno)
        print(f"  After clipping: {len(volc_clipped)}")

        if volc_clipped.empty:
            return

        # Tephra (ash) -- broadest, draw first
        tephra = volc_clipped[volc_clipped["HAZARD_TYPE"] == "Tephra (ash)"]
        if not tephra.empty:
            tephra.plot(ax=ax, color=TEPHRA_COLOR, edgecolor="none", alpha=0.15, zorder=3)
            print(f"  Tephra: {len(tephra)} features")

        # Near-volcano hazards
        near = volc_clipped[volc_clipped["HAZARD_TYPE"] == "Near-volcano hazards"]
        if not near.empty:
            near.plot(ax=ax, color=NEAR_VOLCANO_COLOR, edgecolor="none", alpha=0.35, zorder=3)
            print(f"  Near-volcano: {len(near)} features")

        # Lahars
        lahars = volc_clipped[volc_clipped["HAZARD_TYPE"] == "Lahars"]
        if not lahars.empty:
            lahars.plot(ax=ax, color=LAHAR_COLOR, edgecolor="none", alpha=0.5, zorder=3)
            print(f"  Lahars: {len(lahars)} features")

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch volcanic hazards: {e}")

def fetch_and_render_water_districts(ax, bbox, sno):
    print("\n--- Water Management Districts (outlines) ---")
    sno_geom = make_valid(unary_union(sno.geometry)).buffer(0)

    def clip_district(gdf):
        if gdf.empty:
            return gdf
        gdf = gdf.copy()
        gdf["geometry"] = gdf.geometry.apply(
            lambda g: make_valid(g).intersection(sno_geom)
        )
        return gdf[~gdf.geometry.is_empty]

    layers = [
        (SNOCO_DIKING_LAYER, "Diking", "#2D6A2E", "--"),
        (SNOCO_DRAINAGE_LAYER, "Drainage", "#1565C0", "--"),
        (SNOCO_FLOOD_CTRL_LAYER, "Flood Control", "#E65100", "--"),
    ]

    for layer_id, label, color, ls in layers:
        try:
            gdf = query_arcgis_rest(SNOCO_DISTRICTS_URL, layer_id)
            if gdf.empty:
                print(f"  WARNING: No {label} districts returned.")
                continue
            gdf_c = clip_district(gdf)
            if not gdf_c.empty:
                gdf_c.plot(
                    ax=ax, facecolor="none",
                    edgecolor=color, linewidth=1.5, linestyle=ls,
                    zorder=4,
                )
                print(f"  {label}: {len(gdf_c)} districts")
        except (GEOSException, ValueError, TypeError) as e:
            print(f"  WARNING: Failed to fetch {label} districts: {e}")

def fetch_and_render_public_lands(ax, bbox, sno):
    print("\n--- Public Lands ---")

    # National Forest -- SnoCoWA MapServer layer 34
    try:
        print(f"  Querying National Forest (SnoCoWA layer {SNOCO_FOREST_LAYER})...")
        nf = query_arcgis_rest(SNOCO_DISTRICTS_URL, SNOCO_FOREST_LAYER)
        if not nf.empty:
            nf_clipped = clip_to_county(nf, sno)
            if not nf_clipped.empty:
                nf_clipped.plot(
                    ax=ax, color=NATIONAL_FOREST_COLOR, alpha=0.3,
                    edgecolor="#2D6A2E", linewidth=0.8, zorder=5,
                )
                print(f"  National Forest: {len(nf_clipped)} features")
        else:
            print("  WARNING: No National Forest data returned.")
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch National Forest: {e}")

    # WA State Parks
    try:
        print("  Querying WA State Parks...")
        parks = query_arcgis_rest(WA_STATE_PARKS_URL, 2, bbox_wgs84=bbox)
        if not parks.empty:
            parks_clipped = clip_to_county(parks, sno)
            # Drop small parks (<500 acres / ~2M m²) that render as tiny
            # disconnected artifacts at county scale
            if not parks_clipped.empty:
                parks_clipped = parks_clipped[parks_clipped.geometry.area > 2_000_000]
            if not parks_clipped.empty:
                parks_clipped.plot(
                    ax=ax, color=STATE_PARK_COLOR, alpha=0.5,
                    edgecolor="#2E7D32", linewidth=0.8, zorder=5,
                )
                print(f"  State Parks: {len(parks_clipped)} features")

                # Label larger parks
                name_col = find_name_column(parks_clipped, ["LABEL", "NAME", "UnitName", "name", "Name", "PARKNAME"])
                if name_col:
                    for _, row in parks_clipped.iterrows():
                        geom = row.geometry
                        if geom.is_empty:
                            continue
                        area = geom.area
                        if area < 2_000_000:  # skip small parks
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

    # NPS lands
    try:
        print("  Querying NPS lands (WA only)...")
        nps = query_arcgis_rest(
            NPS_LANDS_URL, 2,
            bbox_wgs84=bbox, where="STATE='WA'",
        )
        if not nps.empty:
            nps_clipped = clip_to_county(nps, sno)
            if not nps_clipped.empty:
                nps_clipped.plot(
                    ax=ax, color="#8D6E63", alpha=0.4,
                    edgecolor="#5D4037", linewidth=0.8, zorder=5,
                )
                print(f"  NPS lands: {len(nps_clipped)} features")
        else:
            print("  WARNING: No NPS data returned.")
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch NPS lands: {e}")

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

        # Render by type
        road_styles = {
            "SR": (STATE_ROUTE_COLOR, 1.5, 7),
            "US": (US_HIGHWAY_COLOR, 2.5, 8),
            "IS": (INTERSTATE_COLOR, 3.0, 8),
        }

        for rt_type in ["SR", "US", "IS"]:  # draw SR first (bottom), then US, then IS
            subset = roads_clipped[roads_clipped["RT_TYPEA"] == rt_type]
            if subset.empty:
                continue
            color, lw, zo = road_styles[rt_type]
            subset.plot(ax=ax, color=color, linewidth=lw, zorder=zo)
            print(f"  {rt_type}: {len(subset)} segments")

        # Label key routes at midpoints
        labeled = set()
        for _, row in roads_clipped.iterrows():
            rt_num = str(row.get("StateRouteNumber", "")).strip()
            rt_type = str(row.get("RT_TYPEA", "")).strip()
            display = str(row.get("DISPLAY", "")).strip()

            if rt_num not in KEY_ROUTES:
                continue
            label_key = f"{rt_type}_{rt_num}"
            if label_key in labeled:
                continue

            geom = row.geometry
            if geom.is_empty:
                continue

            # Get midpoint
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
                fontsize=9, fontweight="bold",
                ha="center", va="center",
                color="#000000",
                path_effects=TEXT_HALO_BOLD, zorder=12,
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                          edgecolor="#888888", alpha=0.85, linewidth=0.5),
            )
            labeled.add(label_key)

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch roads: {e}")

LARGE_CITIES = {"Everett", "Marysville", "Lake Stevens", "Lynnwood"}
SMALL_CITIES = {"Index", "Woodway", "Gold Bar", "Sultan", "Startup", "Darrington"}


def fetch_and_render_cities(ax, bbox, sno):
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

        # Determine name column
        name_col = "NAME"
        if name_col not in cities.columns:
            for c in ["FULL_NAME", "name", "Name"]:
                if c in cities.columns:
                    name_col = c
                    break

        # Draw city boundaries (outlines only)
        cities.plot(
            ax=ax, facecolor="none",
            edgecolor="#333333", linewidth=0.8,
            zorder=9,
        )

        # Label cities with adjustText to resolve overlaps
        from adjustText import adjust_text

        city_texts = []
        city_xs = []
        city_ys = []
        for _, row in cities.iterrows():
            geom = row.geometry
            if geom.is_empty:
                continue
            name = str(row.get(name_col, "")).strip()
            if not name:
                continue

            pt = geom.representative_point()
            city_xs.append(pt.x)
            city_ys.append(pt.y)

            if name in LARGE_CITIES:
                fs, fw = 13, "bold"
            elif name in SMALL_CITIES:
                fs, fw = 9, "normal"
            else:
                fs, fw = 11, "bold"

            t = ax.text(
                pt.x, pt.y, name,
                fontsize=fs, fontweight=fw,
                ha="center", va="center",
                color="#111111",
                path_effects=TEXT_HALO_BOLD, zorder=10,
            )
            city_texts.append(t)

        # Auto-adjust overlapping labels with thin leader lines
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
        # Flood zones
        Patch(facecolor=HIGH_RISK_COLOR, alpha=0.45, edgecolor="none",
              label="Flood Zone: High Risk"),
        Patch(facecolor=MODERATE_RISK_COLOR, alpha=0.45, edgecolor="none",
              label="Flood Zone: Moderate Risk"),
        # Volcanic hazards
        Patch(facecolor=LAHAR_COLOR, alpha=0.5, edgecolor="none",
              label="Lahar Zones"),
        Patch(facecolor=NEAR_VOLCANO_COLOR, alpha=0.35, edgecolor="none",
              label="Near-Volcano Hazards"),
        Patch(facecolor=TEPHRA_COLOR, alpha=0.15, edgecolor="none",
              label="Tephra (Ash Fall)"),
        # Public lands
        Patch(facecolor=NATIONAL_FOREST_COLOR, alpha=0.4, edgecolor="#2D6A2E",
              linewidth=0.8, label="National Forest"),
        Patch(facecolor=STATE_PARK_COLOR, alpha=0.5, edgecolor="#2E7D32",
              linewidth=0.8, label="State Parks"),
        # Roads
        Line2D([0], [0], color=INTERSTATE_COLOR, linewidth=3.0, label="Interstate"),
        Line2D([0], [0], color=US_HIGHWAY_COLOR, linewidth=2.5, label="US Highway"),
        Line2D([0], [0], color=STATE_ROUTE_COLOR, linewidth=1.5, label="State Route"),
        # Water management districts
        Line2D([0], [0], color="#2D6A2E", linewidth=1.5, linestyle="--",
               label="Diking District"),
        Line2D([0], [0], color="#1565C0", linewidth=1.5, linestyle="--",
               label="Drainage District"),
        Line2D([0], [0], color="#E65100", linewidth=1.5, linestyle="--",
               label="Flood Control District"),
    ]

    place_legend(ax, handles, ncol=5, fontsize=14)


def main():
    print("=" * 60)
    print("Snohomish County -- Combined Hazard & Infrastructure Map")
    print("=" * 60)

    # 1. Load base data
    print("\nLoading Snohomish County boundary...")
    sno = load_snohomish_boundary()

    print("Loading land polygons...")
    land = load_land_clipped()

    bbox = get_snohomish_bbox_wgs84()
    print(f"  Snohomish bbox (WGS84): {bbox}")

    # 2. Create base map
    print("\nCreating base map...")
    fig, ax, sno_clipped = create_base_map(
        sno, land=land,
        title="Snohomish County \u2014 Combined Hazard & Infrastructure Map",
    )

    # 3. z=1: Hillshade background
    print("\nFetching hillshade...")
    try:
        img, extent = fetch_hillshade(bbox)
        ax.imshow(img, extent=extent, alpha=0.35, zorder=1, aspect="auto")
        print("  Hillshade rendered.")
    except (urllib.error.URLError, OSError) as e:
        print(f"  WARNING: Failed to fetch hillshade: {e}")

    # 4. z=2: FEMA Flood Zones
    fetch_and_render_flood(ax, bbox, sno)

    # 5. z=3: Volcanic / Lahar Hazards
    fetch_and_render_volcanic(ax, bbox, sno)

    # 6. z=4: Water Management Districts (outlines)
    fetch_and_render_water_districts(ax, bbox, sno)

    # 7. z=5: Public Lands
    fetch_and_render_public_lands(ax, bbox, sno)

    # 8. z=7-8: Roads
    fetch_and_render_roads(ax, bbox, sno)

    # 9. z=9-10: Cities/Towns
    fetch_and_render_cities(ax, bbox, sno)

    # 10. z=11: County border redraw
    print("\nRedrawing county border on top...")
    sno.plot(ax=ax, facecolor="none", edgecolor="#222222", linewidth=1.5, zorder=11)

    # 11. Legend
    build_legend(ax)

    # 12. Attribution — fixed position via layout grid
    place_attribution(ax, "Data: FEMA NFHL, WA DNR, WSDOT, Snohomish County GIS, NPS, USGS")

    # 13. Save
    print(f"\nSaving map to {OUTPUT}...")
    save_map(fig, OUTPUT)
    print("Done!")


if __name__ == "__main__":
    main()

"""
Snohomish County — Evacuation Routes & Bottleneck Analysis Map
Layers: hillshade, FEMA high-risk flood zones, lahar zones,
roads colored by classification, bottleneck highlights where
major roads pass through hazard zones, annotated key bottlenecks,
cities for context.
"""

import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geopandas as gpd
import matplotlib.patheffects as pe
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
from shapely.geometry import LineString, MultiLineString, GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid

from shapely.errors import GEOSException

from snohomish_base import (
    TARGET_CRS,
    FEMA_NFHL_URL,
    FEMA_FLOOD_LAYER,
    VOLCANIC_URL,
    VOLCANIC_LAYER,
    WSDOT_ROUTES_URL,
    SNOCO_DISTRICTS_URL,
    SNOCO_CITIES_LAYER,
    HIGH_RISK_COLOR,
    LAHAR_COLOR,
    INTERSTATE_COLOR,
    HIGH_RISK_ZONES,
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
)

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_evacuation.png")

WSDOT_FC_URL = (
    "https://data.wsdot.wa.gov/arcgis/rest/services/"
    "FunctionalClass/WSDOTFunctionalClassData/MapServer"
)


def extract_lines(geom):
    """Extract only line geometries from a possibly mixed geometry."""
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, (LineString, MultiLineString)):
        return geom
    if isinstance(geom, GeometryCollection):
        lines = [g for g in geom.geoms
                 if isinstance(g, (LineString, MultiLineString))]
        if lines:
            return unary_union(lines) if len(lines) > 1 else lines[0]
    return None


def intersect_lines_with_polygons(lines_gdf, poly_gdf):
    """Return a GeoDataFrame of line segments that intersect hazard polygons.

    For each line feature, compute the geometric intersection with the
    hazard zone union and keep only the line portions inside.
    """
    if lines_gdf.empty or poly_gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs=lines_gdf.crs)

    hazard_union = make_valid(unary_union(poly_gdf.geometry)).buffer(0)

    result_geoms = []
    result_data = []
    for idx, row in lines_gdf.iterrows():
        try:
            inter = make_valid(row.geometry).intersection(hazard_union)
            line_part = extract_lines(inter)
            if line_part is not None and not line_part.is_empty:
                result_geoms.append(line_part)
                result_data.append(row.drop("geometry"))
        except (GEOSException, ValueError, TypeError):
            continue

    if not result_data:
        return gpd.GeoDataFrame(geometry=[], crs=lines_gdf.crs)

    import pandas as pd
    result = gpd.GeoDataFrame(
        pd.DataFrame(result_data),
        geometry=result_geoms,
        crs=lines_gdf.crs,
    )
    return result


def fetch_flood_high_risk(bbox, sno):
    print("\n--- FEMA Flood Zones (high risk only) ---")
    try:
        flood = query_arcgis_rest(
            FEMA_NFHL_URL, FEMA_FLOOD_LAYER, bbox_wgs84=bbox,
            out_fields="FLD_ZONE,ZONE_SUBTY",
        )
        if flood.empty:
            print("  WARNING: No flood zone data returned.")
            return gpd.GeoDataFrame()
        print(f"  Total features: {len(flood)}")

        # Filter to high risk
        flood["zone_clean"] = flood["FLD_ZONE"].astype(str).str.strip().str.upper()
        high = flood[flood["zone_clean"].isin(HIGH_RISK_ZONES)].copy()
        print(f"  High-risk features: {len(high)}")

        if high.empty:
            return gpd.GeoDataFrame()

        high_clipped = clip_to_county(high, sno)
        print(f"  After clipping: {len(high_clipped)}")
        return high_clipped

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch flood zones: {e}")
        return gpd.GeoDataFrame()


def fetch_lahar_zones(bbox, sno):
    print("\n--- Lahar Zones ---")
    try:
        volc = query_arcgis_rest(VOLCANIC_URL, VOLCANIC_LAYER, bbox_wgs84=bbox, out_fields="*")
        if volc.empty:
            print("  WARNING: No volcanic hazard data returned.")
            return gpd.GeoDataFrame()
        print(f"  Total volcanic features: {len(volc)}")

        lahars = volc[volc["HAZARD_TYPE"] == "Lahars"].copy()
        print(f"  Lahar features: {len(lahars)}")

        if lahars.empty:
            return gpd.GeoDataFrame()

        lahars_clipped = clip_to_county(lahars, sno)
        print(f"  After clipping: {len(lahars_clipped)}")
        return lahars_clipped

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch lahar zones: {e}")
        return gpd.GeoDataFrame()

def fetch_state_routes(bbox, sno):
    """Fetch WSDOT state routes (Interstate, US, SR)."""
    print("\n--- WSDOT State Routes ---")
    roads = query_arcgis_rest(
        WSDOT_ROUTES_URL, 0,
        bbox_wgs84=bbox,
        where="RT_TYPEA IN ('IS','US','SR') AND RelRouteType=''",
        out_fields="DISPLAY,RT_TYPEA,StateRouteNumber",
    )
    if roads.empty:
        print("  WARNING: No state route data returned.")
        return gpd.GeoDataFrame()
    print(f"  Total state route features: {len(roads)}")

    roads_clipped = clip_lines_to_county(roads, sno)
    print(f"  After clipping: {len(roads_clipped)}")
    return roads_clipped


def fetch_functional_class_roads(bbox, sno):
    """Fetch WSDOT Functional Class roads for a wider road set."""
    print("\n--- WSDOT Functional Class Roads ---")
    try:
        fc_roads = query_arcgis_rest(
            WSDOT_FC_URL, 0,
            bbox_wgs84=bbox,
            out_fields="FederalFunctionalClassCode,FederalFunctionalClassDesc,RouteIdentifier",
        )
        if fc_roads.empty:
            print("  WARNING: No functional class data returned (0 features). "
                  "Falling back to state routes only.")
            return gpd.GeoDataFrame()
        print(f"  Total FC features: {len(fc_roads)}")

        fc_clipped = clip_lines_to_county(fc_roads, sno)
        print(f"  After clipping: {len(fc_clipped)}")
        return fc_clipped

    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch functional class roads: {e}")
        return gpd.GeoDataFrame()

LARGE_CITIES = {"Everett", "Marysville", "Lake Stevens", "Lynnwood", "Arlington"}
SMALL_CITIES = {"Gold Bar", "Sultan", "Darrington", "Index", "Granite Falls",
                "Snohomish", "Monroe", "Stanwood"}


def fetch_and_render_cities(ax):
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

        # Draw city boundaries (faint outlines)
        cities.plot(
            ax=ax, facecolor="none",
            edgecolor="#555555", linewidth=0.5, linestyle=":",
            zorder=9,
        )

        # Label cities
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
                fs, fw = 11, "bold"
            elif name in SMALL_CITIES:
                fs, fw = 9, "normal"
            else:
                fs, fw = 10, "bold"

            t = ax.text(
                pt.x, pt.y, name,
                fontsize=fs, fontweight=fw,
                ha="center", va="center",
                color="#222222",
                path_effects=TEXT_HALO_BOLD, zorder=15,
            )
            city_texts.append(t)

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

def render_roads(ax, state_routes, fc_roads):
    """Draw roads colored by classification/capacity."""
    print("\n--- Rendering Roads ---")

    # If we have functional class data, draw minor classified roads first
    if not fc_roads.empty and "FederalFunctionalClassCode" in fc_roads.columns:
        # Codes: 1=Interstate, 2=Principal Arterial - Other Freeways,
        # 3=Principal Arterial - Other, 4=Minor Arterial,
        # 5=Major Collector, 6=Minor Collector, 7=Local
        # We only draw codes 3-6 here (state routes handle 1-2)
        fc_roads["fc_code"] = fc_roads["FederalFunctionalClassCode"].astype(str).str.strip()
        minor = fc_roads[fc_roads["fc_code"].isin(["3", "4", "5", "6"])].copy()
        if not minor.empty:
            minor.plot(ax=ax, color="#AAAAAA", linewidth=0.8, zorder=5)
            print(f"  Other classified roads (FC 3-6): {len(minor)} segments")

    # Now draw state routes on top, by type
    if not state_routes.empty:
        road_styles = {
            "SR": ("#444444", 2.0, 7),   # State Route: dark gray
            "US": ("#8B4513", 3.0, 8),   # US Highway: brown
            "IS": (INTERSTATE_COLOR, 4.0, 8),   # Interstate: blue
        }

        for rt_type in ["SR", "US", "IS"]:
            subset = state_routes[state_routes["RT_TYPEA"] == rt_type]
            if subset.empty:
                continue
            color, lw, zo = road_styles[rt_type]
            subset.plot(ax=ax, color=color, linewidth=lw, zorder=zo)
            print(f"  {rt_type}: {len(subset)} segments")



def render_bottleneck_highlights(ax, state_routes, hazard_polys):
    """Draw bright yellow glow behind road segments inside hazard zones."""
    print("\n--- Bottleneck Highlights ---")

    if state_routes.empty or hazard_polys.empty:
        print("  Skipping: no data for intersection.")
        return

    bottleneck_segments = intersect_lines_with_polygons(state_routes, hazard_polys)

    if bottleneck_segments.empty:
        print("  No bottleneck segments found.")
        return

    print(f"  Bottleneck segments: {len(bottleneck_segments)}")

    # Draw thick yellow glow BEHIND the road lines (lower zorder)
    bottleneck_segments.plot(
        ax=ax, color="#FFD600", linewidth=6, alpha=0.7, zorder=6,
    )



KEY_ROUTES = {"5", "2", "9", "530", "92", "20"}


def label_key_routes(ax, state_routes):
    """Place shield-style labels on key routes at their midpoints."""
    if state_routes.empty:
        return

    labeled = set()
    for _, row in state_routes.iterrows():
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
            fontsize=9, fontweight="bold",
            ha="center", va="center",
            color="#000000",
            path_effects=TEXT_HALO_BOLD, zorder=14,
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white",
                      edgecolor="#888888", alpha=0.85, linewidth=0.5),
        )
        labeled.add(label_key)



def annotate_bottlenecks(ax):
    """Mark key evacuation bottleneck locations with arrows and text."""
    print("\n--- Annotating Key Bottlenecks ---")

    # Approximate bottleneck locations in EPSG:2855
    # These are hand-tuned approximate coordinates for the named locations.
    bottlenecks = [
        {
            "label": "SR-530 Oso/Darrington\nLandslide + Lahar Risk",
            "xy": (455_000, 134_000),        # point on SR-530 in valley
            "text_xy": (472_000, 146_000),    # text placement
        },
        {
            "label": "US-2 Sultan/Gold Bar\nSkykomish Flood Zone",
            "xy": (468_000, 100_000),         # point on US-2 near Sultan
            "text_xy": (488_000, 93_000),     # text placement
        },
        {
            "label": "SR-9 Arlington\nFlood Zone Crossing",
            "xy": (435_000, 131_000),         # SR-9 near Arlington
            "text_xy": (410_000, 143_000),    # text placement
        },
        {
            "label": "I-5 Everett Waterfront\nCoastal Flood Risk",
            "xy": (397_000, 110_000),         # I-5 near Everett waterfront
            "text_xy": (378_000, 100_000),    # text placement
        },
    ]

    for bn in bottlenecks:
        ax.annotate(
            bn["label"],
            xy=bn["xy"],
            xytext=bn["text_xy"],
            fontsize=9,
            fontweight="bold",
            color="#B71C1C",
            ha="center", va="center",
            arrowprops=dict(
                arrowstyle="->",
                color="#B71C1C",
                linewidth=1.5,
                connectionstyle="arc3,rad=0.2",
            ),
            bbox=dict(
                boxstyle="round,pad=0.4",
                facecolor="#FFECB3",
                edgecolor="#B71C1C",
                alpha=0.92,
                linewidth=1.2,
            ),
            zorder=16,
            path_effects=[pe.withStroke(linewidth=0.5, foreground="white")],
        )
        print(f"  Annotated: {bn['label'].split(chr(10))[0]}")


def build_legend(ax, has_fc_roads):
    handles = [
        # Road types
        Line2D([0], [0], color=INTERSTATE_COLOR, linewidth=4.0,
               label="Interstate (highest capacity)"),
        Line2D([0], [0], color="#8B4513", linewidth=3.0,
               label="US Highway"),
        Line2D([0], [0], color="#444444", linewidth=2.0,
               label="State Route"),
    ]
    if has_fc_roads:
        handles.append(
            Line2D([0], [0], color="#AAAAAA", linewidth=1.0,
                   label="Other Classified Road"),
        )

    handles.extend([
        # Bottleneck highlight
        Line2D([0], [0], color="#FFD600", linewidth=6.0, alpha=0.7,
               label="Bottleneck (road in hazard zone)"),
        # Hazard zones
        Patch(facecolor=HIGH_RISK_COLOR, alpha=0.25, edgecolor="none",
              label="FEMA High-Risk Flood Zone"),
        Patch(facecolor=LAHAR_COLOR, alpha=0.2, edgecolor="none",
              label="Lahar Zone"),
    ])

    place_legend(ax, handles, ncol=4, fontsize=12)


def main():
    print("=" * 60)
    print("Snohomish County -- Evacuation Routes & Bottlenecks")
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
        title="Snohomish County \u2014 Evacuation Routes & Bottlenecks",
    )

    # 3. Hillshade background (alpha=0.3)
    print("\nFetching hillshade...")
    try:
        img, extent = fetch_hillshade(bbox)
        ax.imshow(img, extent=extent, alpha=0.3, zorder=1, aspect="auto")
        print("  Hillshade rendered.")
    except (urllib.error.URLError, OSError) as e:
        print(f"  WARNING: Failed to fetch hillshade: {e}")

    # 4. Fetch hazard zones
    flood_high = fetch_flood_high_risk(bbox, sno)
    lahars = fetch_lahar_zones(bbox, sno)

    # 5. Draw hazard zones as context layers
    if not flood_high.empty:
        flood_high.plot(ax=ax, color=HIGH_RISK_COLOR, edgecolor="none",
                        alpha=0.25, zorder=2)
        print(f"  Rendered {len(flood_high)} high-risk flood polygons")

    if not lahars.empty:
        lahars.plot(ax=ax, color=LAHAR_COLOR, edgecolor="none",
                    alpha=0.2, zorder=2)
        print(f"  Rendered {len(lahars)} lahar polygons")

    # 6. Fetch roads
    state_routes = fetch_state_routes(bbox, sno)
    fc_roads = fetch_functional_class_roads(bbox, sno)

    # 7. Combine hazard polygons for bottleneck detection
    hazard_parts = []
    if not flood_high.empty:
        hazard_parts.append(flood_high)
    if not lahars.empty:
        hazard_parts.append(lahars)

    if hazard_parts:
        import pandas as pd
        all_hazards = gpd.GeoDataFrame(
            pd.concat(hazard_parts, ignore_index=True),
            crs=TARGET_CRS,
        )
    else:
        all_hazards = gpd.GeoDataFrame(geometry=[], crs=TARGET_CRS)

    # 8. Render bottleneck highlights (BEFORE roads so glow is behind)
    render_bottleneck_highlights(ax, state_routes, all_hazards)

    # 9. Render roads on top of highlights
    render_roads(ax, state_routes, fc_roads)

    # 10. Label key routes
    label_key_routes(ax, state_routes)

    # 11. Cities for context
    fetch_and_render_cities(ax)

    # 12. Redraw county border
    sno.plot(ax=ax, facecolor="none", edgecolor="#222222",
             linewidth=1.5, zorder=11)

    # 13. Annotate known bottlenecks
    annotate_bottlenecks(ax)

    # 14. Legend
    build_legend(ax, has_fc_roads=not fc_roads.empty)

    # 15. Attribution
    place_attribution(
        ax,
        "Data: WSDOT State Routes & Functional Class, FEMA NFHL, "
        "WA DNR Volcanic Hazards, Snohomish County GIS, USGS"
    )

    # 16. Save
    print(f"\nSaving map to {OUTPUT}...")
    save_map(fig, OUTPUT)
    print("Done!")


if __name__ == "__main__":
    main()

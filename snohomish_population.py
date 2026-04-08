"""
Snohomish County — Population Density & Hazard Exposure Map

Generates a choropleth of Census 2020 block group population density
overlaid with FEMA flood zone and lahar zone boundaries for
emergency management exposure analysis.
"""

import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
from shapely.ops import unary_union
from shapely.validation import make_valid

from shapely.errors import GEOSException

from snohomish_base import (
    MAP_XLIM, MAP_YLIM,
    FEMA_NFHL_URL, FEMA_FLOOD_LAYER,
    VOLCANIC_URL, VOLCANIC_LAYER,
    SNOCO_DISTRICTS_URL, SNOCO_CITIES_LAYER,
    load_snohomish_boundary, load_land_clipped, get_snohomish_bbox_wgs84,
    fetch_hillshade, create_base_map, clip_to_land,
    query_arcgis_rest, place_legend, place_attribution, save_map,
)

TIGER_TRACTS_URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer"
LAHAR_URL = VOLCANIC_URL

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_population.png")


def main():
    # 1. Load county boundary and land mask
    print("Loading county boundary and land...")
    sno = load_snohomish_boundary()
    land = load_land_clipped()
    bbox = get_snohomish_bbox_wgs84()

    # 2. Fetch Census Block Groups
    print("Fetching Census Block Groups (layer 10)...")
    bg = query_arcgis_rest(
        TIGER_TRACTS_URL, 10,
        where="STATE='53' AND COUNTY='061'",
        out_fields="GEOID,POP100,AREALAND",
    )
    print(f"  Block groups received: {len(bg)}")

    # Calculate population density (people per km²)
    bg["AREALAND"] = bg["AREALAND"].astype(float)
    bg["POP100"] = bg["POP100"].astype(float)
    bg["density"] = bg["POP100"] / (bg["AREALAND"] / 1_000_000)
    bg["density"] = bg["density"].fillna(0)

    # Clip block groups to county boundary (projected)
    sno_union = make_valid(unary_union(sno.geometry))
    bg["geometry"] = bg.geometry.apply(
        lambda g: make_valid(make_valid(g).intersection(sno_union))
    )
    bg = bg[~bg.geometry.is_empty].copy()

    # Also clip to land
    bg = clip_to_land(bg, land)
    print(f"  Block groups after clipping: {len(bg)}")

    # 3. Fetch hazard zones
    print("Fetching FEMA flood zones (high-risk)...")
    flood = query_arcgis_rest(
        FEMA_NFHL_URL, FEMA_FLOOD_LAYER,
        bbox_wgs84=bbox,
        out_fields="FLD_ZONE,ZONE_SUBTY",
    )
    # Keep only high-risk zones (A and V zones)
    if len(flood) > 0:
        flood = flood[flood["FLD_ZONE"].str.startswith(("A", "V"), na=False)].copy()
        flood["geometry"] = flood.geometry.apply(lambda g: make_valid(g))
        print(f"  High-risk flood polygons: {len(flood)}")
    else:
        print("  WARNING: No flood data returned")

    print("Fetching lahar zones...")
    lahar = query_arcgis_rest(LAHAR_URL, VOLCANIC_LAYER, bbox_wgs84=bbox)
    if len(lahar) > 0:
        # Filter to lahars only (exclude tephra and near-volcano)
        if "HAZARD_TYPE" in lahar.columns:
            lahar = lahar[lahar["HAZARD_TYPE"] == "Lahars"].copy()
        lahar["geometry"] = lahar.geometry.apply(lambda g: make_valid(g))
        # Clip lahar zones to county boundary
        lahar["geometry"] = lahar.geometry.apply(
            lambda g: make_valid(make_valid(g).intersection(sno_union))
        )
        lahar = lahar[~lahar.geometry.is_empty].copy()
        print(f"  Lahar polygons (clipped): {len(lahar)}")
    else:
        print("  WARNING: No lahar data returned")

    # 4. Population exposure analysis
    print("\n=== POPULATION EXPOSURE ANALYSIS ===")

    if len(flood) > 0:
        flood_union = make_valid(unary_union(flood.geometry))
        flood_exposed = bg[bg.geometry.intersects(flood_union)]
        flood_pop = flood_exposed["POP100"].sum()
        print(f"  FEMA Flood (high-risk): {int(flood_pop):,} people in {len(flood_exposed)} block groups")
    else:
        flood_pop = 0
        print("  FEMA Flood: no data available")

    if len(lahar) > 0:
        lahar_union = make_valid(unary_union(lahar.geometry))
        lahar_exposed = bg[bg.geometry.intersects(lahar_union)]
        lahar_pop = lahar_exposed["POP100"].sum()
        print(f"  Lahar zones: {int(lahar_pop):,} people in {len(lahar_exposed)} block groups")
    else:
        lahar_pop = 0
        print("  Lahar: no data available")

    total_pop = bg["POP100"].sum()
    print(f"\n  Total county population (Census 2020): {int(total_pop):,}")
    print(f"  Flood-exposed: {flood_pop/total_pop*100:.1f}%" if total_pop > 0 else "")
    print(f"  Lahar-exposed: {lahar_pop/total_pop*100:.1f}%" if total_pop > 0 else "")
    print("=" * 44)

    # 5. Fetch city labels
    print("\nFetching city labels...")
    try:
        cities = query_arcgis_rest(SNOCO_DISTRICTS_URL, SNOCO_CITIES_LAYER, out_fields="NAME,FULL_NAME")
        print(f"  Cities: {len(cities)}")
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch cities: {e}")
        cities = gpd.GeoDataFrame()

    # 6. Create the map
    print("\nRendering map...")
    fig, ax, sno_clipped = create_base_map(
        sno, land=land,
        title="Snohomish County \u2014 Population Density & Hazard Exposure",
    )

    # Hillshade
    try:
        img, extent = fetch_hillshade(bbox)
        ax.imshow(img, extent=extent, zorder=1, alpha=0.2)
    except (urllib.error.URLError, OSError) as e:
        print(f"  Hillshade failed: {e}")

    # Choropleth
    bounds_list = [0, 100, 500, 1000, 2000, 5000, 10000]
    cmap = plt.cm.YlOrRd
    norm = mcolors.BoundaryNorm(bounds_list, cmap.N, clip=True)

    bg.plot(
        ax=ax,
        column="density",
        cmap=cmap,
        norm=norm,
        edgecolor="#888888",
        linewidth=0.2,
        alpha=0.7,
        zorder=5,
    )

    # Hazard overlays (outline only)
    if len(flood) > 0:
        flood.boundary.plot(
            ax=ax,
            color="red",
            linewidth=1.5,
            linestyle="--",
            zorder=10,
        )

    if len(lahar) > 0:
        lahar.boundary.plot(
            ax=ax,
            color="purple",
            linewidth=1.5,
            linestyle="--",
            zorder=10,
        )

    # Re-draw county boundary on top
    sno_clipped.plot(ax=ax, facecolor="none", edgecolor="#444444", linewidth=1.2, zorder=12)

    # Colorbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(
        sm, ax=ax,
        orientation="vertical",
        fraction=0.025,
        pad=0.01,
        aspect=30,
        shrink=0.55,
    )
    cbar.set_label("Population Density (people / km\u00b2)", fontsize=12)
    cbar.set_ticks(bounds_list)
    cbar.set_ticklabels(["0", "100", "500", "1k", "2k", "5k", "10k+"])

    # City labels
    if len(cities) > 0:
        name_col = "NAME"
        if name_col not in cities.columns:
            for c in ["FULL_NAME", "name", "Name"]:
                if c in cities.columns:
                    name_col = c
                    break

        for _, row in cities.iterrows():
            geom = row.geometry
            if geom.is_empty:
                continue
            name = str(row.get(name_col, "")).strip()
            if not name:
                continue
            pt = geom.representative_point()
            # Only label if inside map extent
            if not (MAP_XLIM[0] <= pt.x <= MAP_XLIM[1] and MAP_YLIM[0] <= pt.y <= MAP_YLIM[1]):
                continue
            ax.plot(pt.x, pt.y, "ko", markersize=3, zorder=15)
            ax.annotate(
                name,
                xy=(pt.x, pt.y),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=9,
                fontweight="bold",
                zorder=15,
                path_effects=[pe.withStroke(linewidth=3, foreground="white")],
            )

    # Legend (hazard overlays)
    legend_handles = []
    if len(flood) > 0:
        legend_handles.append(
            Line2D([0], [0], color="red", linewidth=1.5, linestyle="--",
                   label=f"FEMA Flood (high-risk) \u2014 {int(flood_pop):,} exposed")
        )
    if len(lahar) > 0:
        legend_handles.append(
            Line2D([0], [0], color="purple", linewidth=1.5, linestyle="--",
                   label=f"Lahar Zone \u2014 {int(lahar_pop):,} exposed")
        )
    if legend_handles:
        place_legend(ax, legend_handles, ncol=2, fontsize=11)

    # Attribution
    place_attribution(ax, "Data: US Census Bureau (2020), FEMA NFHL, WA DNR")

    # Save
    save_map(fig, OUTPUT)
    print("\nDone!")


if __name__ == "__main__":
    main()

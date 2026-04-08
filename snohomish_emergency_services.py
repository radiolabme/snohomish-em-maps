"""
Map 3 — Snohomish County Fire & Hospital Districts
Queries fire protection districts, regional fire authority, and hospital districts
from Snohomish County ArcGIS MapServer, renders them on the county base map.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geopandas as gpd
import matplotlib.patheffects as pe
from matplotlib.patches import Patch
from shapely.validation import make_valid

from snohomish_base import (
    TARGET_CRS,
    SNOCO_DISTRICTS_URL,
    SNOCO_SNOCO_FIRE_LAYER,
    SNOCO_SNOCO_HOSPITAL_LAYER,
    load_snohomish_boundary,
    load_land_clipped,
    query_arcgis_rest,
    create_base_map,
    save_map,
)

DISTRICTS_URL = SNOCO_DISTRICTS_URL
RFA_LAYER = 30         # North County Regional Fire Authority

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_emergency_services.png")

# Warm palette for fire districts (reds, oranges, yellows, warm tones)
WARM_COLORS = [
    "#E63946",  # red
    "#F4A261",  # sandy orange
    "#E76F51",  # burnt sienna
    "#D4A017",  # goldenrod
    "#FF6B35",  # orange
    "#C44536",  # dark red
    "#F2CC8F",  # buff
    "#E07A5F",  # terracotta
    "#BC6C25",  # raw sienna
    "#DDA15E",  # sandy brown
    "#FFBA08",  # amber
    "#D62828",  # crimson
    "#F77F00",  # tangerine
    "#CC5803",  # rust
    "#9B2226",  # maroon
    "#AE2012",  # dark rust
    "#BB3E03",  # burnt orange
    "#CA6702",  # alloy orange
    "#EE9B00",  # gamboge
    "#E9D8A6",  # vanilla
    "#FFD166",  # mustard yellow
    "#F4845F",  # salmon
    "#F3722C",  # orange soda
    "#F94144",  # red salsa
    "#F8961E",  # yellow orange
    "#F9C74F",  # maize
    "#90BE6D",  # pistachio (fallback)
    "#577590",  # queen blue (fallback)
]


def main():
    print("Loading county boundary...")
    sno = load_snohomish_boundary()

    print("Loading land (coastline clipping)...")
    land = load_land_clipped()

    # Query data
    print("Querying Fire Protection Districts (layer 31)...")
    fire = query_arcgis_rest(DISTRICTS_URL, SNOCO_FIRE_LAYER)
    print(f"  Got {len(fire)} fire district polygons")

    print("Querying North County Regional Fire Authority (layer 30)...")
    rfa = query_arcgis_rest(DISTRICTS_URL, RFA_LAYER)
    print(f"  Got {len(rfa)} RFA polygons")

    print("Querying Hospital Districts (layer 33)...")
    hospital = query_arcgis_rest(DISTRICTS_URL, SNOCO_HOSPITAL_LAYER)
    print(f"  Got {len(hospital)} hospital district polygons")

    # Determine the district name field
    def find_district_field(gdf, label):
        """Find the district name field, case-insensitive."""
        for col in gdf.columns:
            if col.lower() == "district":
                return col
        # Fallback: look for anything with 'name' or 'district'
        for col in gdf.columns:
            if "name" in col.lower() or "dist" in col.lower():
                return col
        print(f"  Warning: no district field found for {label}. Columns: {list(gdf.columns)}")
        return None

    fire_field = find_district_field(fire, "fire") if len(fire) > 0 else None
    rfa_field = find_district_field(rfa, "RFA") if len(rfa) > 0 else None
    hosp_field = find_district_field(hospital, "hospital") if len(hospital) > 0 else None

    # Merge fire + RFA into one combined GeoDataFrame
    all_fire_rows = []
    if len(fire) > 0 and fire_field:
        fire_clean = fire[[fire_field, "geometry"]].copy()
        fire_clean = fire_clean.rename(columns={fire_field: "district_name"})
        all_fire_rows.append(fire_clean)

    if len(rfa) > 0 and rfa_field:
        rfa_clean = rfa[[rfa_field, "geometry"]].copy()
        rfa_clean = rfa_clean.rename(columns={rfa_field: "district_name"})
        all_fire_rows.append(rfa_clean)

    if all_fire_rows:
        all_fire = gpd.GeoDataFrame(
            data=__import__("pandas").concat(all_fire_rows, ignore_index=True),
            crs=TARGET_CRS,
        )
    else:
        print("ERROR: No fire district data retrieved!")
        return

    # Clean geometry
    all_fire["geometry"] = all_fire.geometry.apply(lambda g: make_valid(g).buffer(0))

    # Clip to county boundary
    sno_geom = sno.geometry.iloc[0]
    all_fire["geometry"] = all_fire.geometry.apply(
        lambda g: make_valid(g.intersection(sno_geom))
    )
    all_fire = all_fire[~all_fire.geometry.is_empty].copy()

    # Get unique district names and assign colors
    district_names = sorted(all_fire["district_name"].dropna().unique())
    print(f"  {len(district_names)} unique fire/RFA districts: {district_names}")

    color_map = {}
    for i, name in enumerate(district_names):
        color_map[name] = WARM_COLORS[i % len(WARM_COLORS)]

    # Prepare hospital districts
    if len(hospital) > 0 and hosp_field:
        hospital_clean = hospital[[hosp_field, "geometry"]].copy()
        hospital_clean = hospital_clean.rename(columns={hosp_field: "district_name"})
        hospital_clean["geometry"] = hospital_clean.geometry.apply(
            lambda g: make_valid(g).buffer(0)
        )
        hospital_clean["geometry"] = hospital_clean.geometry.apply(
            lambda g: make_valid(g.intersection(sno_geom))
        )
        hospital_clean = hospital_clean[~hospital_clean.geometry.is_empty].copy()
        hosp_names = sorted(hospital_clean["district_name"].dropna().unique())
        print(f"  {len(hosp_names)} hospital districts: {hosp_names}")
    else:
        hospital_clean = gpd.GeoDataFrame()
        hosp_names = []

    # Create base map
    print("Rendering base map...")
    fig, ax, sno_clipped = create_base_map(
        sno, land,
        title="Snohomish County — Fire & Hospital Districts"
    )

    # Render fire districts
    print("Rendering fire districts...")
    for name in district_names:
        subset = all_fire[all_fire["district_name"] == name]
        color = color_map[name]
        subset.plot(ax=ax, color=color, alpha=0.5, edgecolor="#333333",
                    linewidth=0.4)

    # Render hospital districts (hatched overlay with dashed borders)
    if len(hospital_clean) > 0:
        print("Rendering hospital districts...")
        hosp_colors = ["#4361EE", "#7209B7", "#3A0CA3"]
        for i, name in enumerate(hosp_names):
            subset = hospital_clean[hospital_clean["district_name"] == name]
            c = hosp_colors[i % len(hosp_colors)]
            # Hatched fill with dashed border
            subset.plot(ax=ax, facecolor="none", edgecolor=c,
                        linewidth=2.5, linestyle="--", hatch="///",
                        alpha=0.7)

    # Label fire districts
    print("Labeling fire districts...")
    for name in district_names:
        subset = all_fire[all_fire["district_name"] == name]
        # Use the representative point of the largest polygon for label placement
        if len(subset) == 0:
            continue
        # Dissolve to get the combined geometry for this district
        combined = subset.dissolve()
        rep_pt = combined.geometry.iloc[0].representative_point()

        # Shorten label if it's too long
        label = str(name)
        if len(label) > 25:
            label = label[:22] + "..."

        ax.annotate(
            label,
            xy=(rep_pt.x, rep_pt.y),
            fontsize=8,
            fontweight="bold",
            ha="center", va="center",
            color="#222222",
            path_effects=[
                pe.withStroke(linewidth=3, foreground="white"),
            ],
        )

    # Legend
    print("Building legend...")
    legend_elements = []

    # Fire district entries
    for name in district_names:
        legend_elements.append(
            Patch(facecolor=color_map[name], edgecolor="#333333",
                  alpha=0.6, label=str(name))
        )

    # Separator: blank entry
    legend_elements.append(Patch(facecolor="none", edgecolor="none", label=""))

    # Hospital district entries
    hosp_colors_legend = ["#4361EE", "#7209B7", "#3A0CA3"]
    for i, name in enumerate(hosp_names):
        c = hosp_colors_legend[i % len(hosp_colors_legend)]
        legend_elements.append(
            Patch(facecolor="none", edgecolor=c, linewidth=2,
                  linestyle="--", hatch="///", alpha=0.7,
                  label=f"Hospital: {name}")
        )

    leg = ax.legend(
        handles=legend_elements,
        loc="lower center",
        fontsize=10,
        frameon=True,
        framealpha=0.9,
        edgecolor="#CCCCCC",
        title="Districts",
        title_fontsize=12,
        ncol=4,
        columnspacing=1.0,
        handlelength=1.5,
    )

    # Save
    print("Saving map...")
    save_map(fig, OUTPUT)
    print("Done!")


if __name__ == "__main__":
    main()

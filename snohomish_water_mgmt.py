"""
Map 4 — Snohomish County Water Management Districts
Queries diking, drainage, and flood control districts from Snohomish County GIS
and renders them on a base map.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib.patheffects as pe
from matplotlib.patches import Patch

from snohomish_base import (
    SNOCO_DISTRICTS_URL,
    SNOCO_DIKING_LAYER,
    SNOCO_DRAINAGE_LAYER,
    SNOCO_FLOOD_CTRL_LAYER,
    load_snohomish_boundary,
    load_land_clipped,
    query_arcgis_rest,
    create_base_map,
    save_map,
    clip_to_county,
)

BASE_URL = SNOCO_DISTRICTS_URL

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_water_mgmt.png")


def fetch_districts():
    """Fetch all three district layers."""
    print(f"Fetching Diking Districts (layer {SNOCO_DIKING_LAYER})...")
    diking = query_arcgis_rest(BASE_URL, SNOCO_DIKING_LAYER)
    print(f"  Got {len(diking)} diking districts")

    print(f"Fetching Drainage Districts (layer {SNOCO_DRAINAGE_LAYER})...")
    drainage = query_arcgis_rest(BASE_URL, SNOCO_DRAINAGE_LAYER)
    print(f"  Got {len(drainage)} drainage districts")

    print(f"Fetching Flood Control Districts (layer {SNOCO_FLOOD_CTRL_LAYER})...")
    flood = query_arcgis_rest(BASE_URL, SNOCO_FLOOD_CTRL_LAYER)
    print(f"  Got {len(flood)} flood districts")

    return diking, drainage, flood


def plot_districts(ax, diking, drainage, flood, sno_boundary):
    """Plot all three district types with distinct styles."""

    # Clip districts to county boundary
    diking_c = clip_to_county(diking, sno_boundary)
    drainage_c = clip_to_county(drainage, sno_boundary)
    flood_c = clip_to_county(flood, sno_boundary)

    # --- Flood Control Districts (orange/amber, solid border) ---
    if not flood_c.empty:
        flood_c.plot(
            ax=ax,
            color="#E8A020",
            alpha=0.4,
            edgecolor="#B87800",
            linewidth=1.0,
            linestyle="-",
            zorder=3,
        )

    # --- Drainage Districts (blue, dashed border) ---
    if not drainage_c.empty:
        drainage_c.plot(
            ax=ax,
            color="#4488CC",
            alpha=0.3,
            edgecolor="#2266AA",
            linewidth=1.0,
            linestyle="--",
            zorder=4,
        )

    # --- Diking Districts (green, solid border) ---
    if not diking_c.empty:
        diking_c.plot(
            ax=ax,
            color="#44AA44",
            alpha=0.4,
            edgecolor="#228822",
            linewidth=1.0,
            linestyle="-",
            zorder=5,
        )

    # --- Labels ---
    text_effects = [
        pe.withStroke(linewidth=3, foreground="white"),
    ]

    def label_districts(gdf, fontsize=10, color="#000000"):
        if gdf.empty:
            return
        # Determine the name field
        name_col = None
        for col in ["Name", "name", "NAME"]:
            if col in gdf.columns:
                name_col = col
                break
        if name_col is None:
            return

        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom.is_empty:
                continue
            name = row[name_col]
            if not name or str(name).strip() == "":
                continue
            # Use representative point for label placement
            pt = geom.representative_point()
            # Only label if area is large enough to fit text
            area_km2 = geom.area / 1e6
            if area_km2 < 2:
                fontsize_use = max(6, fontsize - 3)
            elif area_km2 < 10:
                fontsize_use = max(7, fontsize - 1)
            else:
                fontsize_use = fontsize

            # Skip very tiny districts
            if area_km2 < 0.5:
                continue

            label = str(name).strip()

            # Wrap long labels
            if len(label) > 25:
                words = label.split()
                mid = len(words) // 2
                label = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])

            ax.text(
                pt.x, pt.y, label,
                fontsize=fontsize_use,
                ha="center", va="center",
                fontweight="bold",
                color=color,
                path_effects=text_effects,
                zorder=10,
            )

    label_districts(flood_c, fontsize=9, color="#7A4A00")
    label_districts(drainage_c, fontsize=9, color="#1A4488")
    label_districts(diking_c, fontsize=9, color="#1A6622")


def build_legend(ax):
    """Add a legend for the three district types."""
    legend_elements = [
        Patch(facecolor="#44AA44", alpha=0.5, edgecolor="#228822",
              linewidth=1.5, label="Diking Districts"),
        Patch(facecolor="#4488CC", alpha=0.4, edgecolor="#2266AA",
              linewidth=1.5, linestyle="--", label="Drainage Districts"),
        Patch(facecolor="#E8A020", alpha=0.5, edgecolor="#B87800",
              linewidth=1.5, label="Flood Control Districts"),
    ]

    leg = ax.legend(
        handles=legend_elements,
        loc="lower right",
        fontsize=14,
        frameon=True,
        fancybox=True,
        framealpha=0.9,
        edgecolor="#666666",
        title="Water Management Districts",
        title_fontsize=14,
    )
    leg.set_zorder(20)


def main():
    print("=" * 60)
    print("Map 4: Snohomish County — Water Management Districts")
    print("=" * 60)

    print("\nLoading Snohomish County boundary...")
    sno = load_snohomish_boundary()

    print("Loading coastline data...")
    land = load_land_clipped()

    diking, drainage, flood = fetch_districts()

    print("\nCreating base map...")
    fig, ax, sno_clipped = create_base_map(
        sno, land=land,
        title="Snohomish County — Water Management Districts"
    )

    print("Plotting districts...")
    plot_districts(ax, diking, drainage, flood, sno)

    build_legend(ax)

    print(f"\nSaving map to {OUTPUT}...")
    save_map(fig, OUTPUT)
    print("Done!")


if __name__ == "__main__":
    main()

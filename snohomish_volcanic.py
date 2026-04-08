"""
Map 2 — Snohomish County: Volcanic & Lahar Hazards
Queries WA DNR Simplified Volcanic Hazards (USGS) layer and renders
lahar, near-volcano, and tephra zones clipped to Snohomish County.

Note: WA DNR Ground Response / Liquefaction layer was attempted but the
MapServer returns null geometries for all features, so it is skipped.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from matplotlib.patches import Patch

from snohomish_base import (
    VOLCANIC_URL,
    VOLCANIC_LAYER,
    LAHAR_COLOR,
    NEAR_VOLCANO_COLOR,
    TEPHRA_COLOR,
    load_snohomish_boundary,
    load_land_clipped,
    get_snohomish_bbox_wgs84,
    query_arcgis_rest,
    create_base_map,
    save_map,
    clip_to_county,
)

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_volcanic.png")

# Layer 0 field HAZARD_TYPE has values: Lahars, Near-volcano hazards, Tephra (ash)
# Layer 0 field VOLCANO has values: Glacier Peak, Mount Baker, All volcanoes
HAZARD_COLORS = {
    "Lahars":                LAHAR_COLOR,
    "Near-volcano hazards":  NEAR_VOLCANO_COLOR,
    "Tephra (ash)":          TEPHRA_COLOR,
}
HAZARD_ALPHA = 0.6

# Draw order: broadest / least severe first so more specific zones overlay
DRAW_ORDER = ["Tephra (ash)", "Near-volcano hazards", "Lahars"]


def main():
    print("=== Map 2: Volcanic & Lahar Hazards ===")

    # 1. Load base data
    print("Loading Snohomish County boundary...")
    sno = load_snohomish_boundary()

    print("Loading land polygons...")
    land = load_land_clipped()

    bbox = get_snohomish_bbox_wgs84()
    print(f"  Snohomish bbox (WGS84): {bbox}")

    # 2. Query volcanic hazards — Layer 0 (Simplified Volcanic Hazards, USGS)
    print(f"\nQuerying WA DNR Volcanic Hazards (layer {VOLCANIC_LAYER})...")
    volc = query_arcgis_rest(VOLCANIC_URL, VOLCANIC_LAYER, bbox_wgs84=bbox, out_fields="*")

    if volc.empty:
        print("  ERROR: No volcanic hazard features returned. Cannot build map.")
        return

    print(f"  Got {len(volc)} features")
    print(f"  HAZARD_TYPE: {list(volc['HAZARD_TYPE'].unique())}")
    print(f"  VOLCANO:     {list(volc['VOLCANO'].unique())}")

    # Clip to county boundary
    print("  Clipping to Snohomish County...")
    volc_clipped = clip_to_county(volc, sno)
    print(f"  After clipping: {len(volc_clipped)} features")

    if volc_clipped.empty:
        print("  ERROR: No features remain after clipping.")
        return

    # 3. Create the base map
    print("\nCreating base map...")
    fig, ax, sno_clipped = create_base_map(
        sno, land,
        title="Snohomish County \u2014 Volcanic & Lahar Hazards",
    )

    legend_handles = []

    # 4. Render volcanic hazard zones in draw order
    print("  Rendering volcanic hazard zones...")
    for htype in DRAW_ORDER:
        subset = volc_clipped[volc_clipped["HAZARD_TYPE"] == htype]
        if subset.empty:
            continue

        color = HAZARD_COLORS.get(htype, "#E53E3E")

        # Build label including source volcanoes
        volcanoes = sorted(subset["VOLCANO"].dropna().unique())
        label = htype
        if volcanoes:
            label += f"  ({', '.join(volcanoes)})"

        subset.plot(ax=ax, color=color, edgecolor="none", alpha=HAZARD_ALPHA)
        legend_handles.append(
            Patch(facecolor=color, alpha=HAZARD_ALPHA, label=label)
        )
        print(f"    {htype}: {len(subset)} feature(s) — volcanoes: {volcanoes}")

    # 5. Redraw county border on top
    sno_clipped.plot(ax=ax, facecolor="none", edgecolor="#444444", linewidth=1.2)

    # 6. Legend
    if legend_handles:
        ax.legend(
            handles=legend_handles,
            loc="lower right",
            fontsize=14,
            framealpha=0.92,
            edgecolor="#999999",
            title="Hazard Types",
            title_fontsize=14,
            fancybox=True,
        )

    # 7. Attribution note
    ax.annotate(
        "Data: WA DNR / USGS Simplified Volcanic Hazards",
        xy=(0.01, 0.01), xycoords="axes fraction",
        fontsize=9, color="#666666", ha="left", va="bottom",
    )

    # 8. Save
    print("\nSaving map...")
    save_map(fig, OUTPUT)
    print("Done.")


if __name__ == "__main__":
    main()

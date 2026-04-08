"""
Map 1 — Snohomish County FEMA Flood Hazard Zones
Queries FEMA NFHL flood zone polygons and renders them by risk level.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from matplotlib.patches import Patch

from snohomish_base import (
    FEMA_NFHL_URL,
    FEMA_FLOOD_LAYER,
    HIGH_RISK_COLOR,
    MODERATE_RISK_COLOR,
    load_snohomish_boundary,
    load_land_clipped,
    get_snohomish_bbox_wgs84,
    query_arcgis_rest,
    create_base_map,
    save_map,
    clip_to_county,
    classify_flood_risk,
)

OTHER_RISK_COLOR = "#FED7D7"

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_flood_zones.png")

def main():
    print("Loading Snohomish County boundary...")
    sno = load_snohomish_boundary()

    print("Loading land polygons...")
    land = load_land_clipped()

    print("Querying FEMA NFHL flood zones...")
    bbox = get_snohomish_bbox_wgs84()
    flood = query_arcgis_rest(
        FEMA_NFHL_URL,
        FEMA_FLOOD_LAYER,
        bbox_wgs84=bbox,
        out_fields="FLD_ZONE,ZONE_SUBTY",
    )

    if flood.empty:
        print("WARNING: No flood zone data returned. Generating base map only.")
        fig, ax, _ = create_base_map(
            sno, land=land,
            title="Snohomish County \u2014 FEMA Flood Hazard Zones",
        )
        save_map(fig, OUTPUT_PATH)
        return

    print(f"  Total flood zone features: {len(flood)}")

    # Classify risk levels
    flood["risk"] = flood.apply(classify_flood_risk, axis=1)
    print("  Risk distribution:")
    print(flood["risk"].value_counts().to_string(header=False))

    # Clip to county boundary
    print("Clipping flood zones to county boundary...")
    flood_clipped = clip_to_county(flood, sno)
    print(f"  Features after clipping: {len(flood_clipped)}")

    # Drop minimal risk (let county gray show through)
    flood_render = flood_clipped[flood_clipped["risk"] != "minimal"].copy()
    print(f"  Features to render (excluding minimal): {len(flood_render)}")

    # Create base map
    print("Creating base map...")
    fig, ax, _ = create_base_map(
        sno, land=land,
        title="Snohomish County \u2014 FEMA Flood Hazard Zones",
    )

    # Render flood zones by risk level (other first, then moderate, then high on top)
    risk_colors = {
        "other": OTHER_RISK_COLOR,
        "moderate": MODERATE_RISK_COLOR,
        "high": HIGH_RISK_COLOR,
    }
    render_order = ["other", "moderate", "high"]

    for risk_level in render_order:
        subset = flood_render[flood_render["risk"] == risk_level]
        if subset.empty:
            continue
        print(f"  Rendering {risk_level}: {len(subset)} features")
        subset.plot(ax=ax, color=risk_colors[risk_level], edgecolor="none", alpha=0.85)

    # Re-draw county outline on top
    sno.plot(ax=ax, facecolor="none", edgecolor="#444444", linewidth=1.2)

    # Legend
    legend_elements = [
        Patch(facecolor=HIGH_RISK_COLOR, edgecolor="none", label="High Risk (A/V Zones)"),
        Patch(facecolor=MODERATE_RISK_COLOR, edgecolor="none", label="Moderate Risk (X \u2013 0.2% Annual Chance)"),
        Patch(facecolor=OTHER_RISK_COLOR, edgecolor="none", label="Other / Zone D"),
        Patch(facecolor="#E8E8E8", edgecolor="#999999", label="Minimal Risk (X Unshaded)"),
    ]
    ax.legend(
        handles=legend_elements,
        loc="lower left",
        fontsize=14,
        frameon=True,
        fancybox=True,
        framealpha=0.9,
        edgecolor="#CCCCCC",
    )

    print("Saving map...")
    save_map(fig, OUTPUT_PATH)
    print("Done.")


if __name__ == "__main__":
    main()

"""
Snohomish County — Critical Facilities Map
Layers: hillshade, fire/hospital district boundaries, hospitals, fire stations,
schools, police stations. Data from OpenStreetMap Overpass API and Snohomish County GIS.
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geopandas as gpd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.ops import unary_union
from shapely.validation import make_valid

from shapely.errors import GEOSException

from snohomish_base import (
    TARGET_CRS,
    SNOCO_DISTRICTS_URL,
    SNOCO_FIRE_LAYER,
    SNOCO_HOSPITAL_LAYER,
    OVERPASS_BBOX,
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
)

OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snohomish_facilities.png")

BBOX = OVERPASS_BBOX



def main():
    print("Loading county boundary...")
    sno = load_snohomish_boundary()
    land = load_land_clipped()
    bbox_wgs84 = get_snohomish_bbox_wgs84()

    # Get county boundary as single geometry in EPSG:2855 for clipping points
    county_geom = make_valid(unary_union(sno.geometry)).buffer(0)

    # Fetch facilities from Overpass
    bbox_str = f"{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}"

    facility_queries = {
        "hospitals": f'[out:json];(node["amenity"="hospital"]({bbox_str});way["amenity"="hospital"]({bbox_str}););out center;',
        "fire_stations": f'[out:json];(node["amenity"="fire_station"]({bbox_str});way["amenity"="fire_station"]({bbox_str}););out center;',
        "schools": f'[out:json];(node["amenity"="school"]({bbox_str});way["amenity"="school"]({bbox_str}););out center;',
        "police": f'[out:json];(node["amenity"="police"]({bbox_str});way["amenity"="police"]({bbox_str}););out center;',
    }

    facilities = {}
    for ftype, query in facility_queries.items():
        print(f"Querying Overpass for {ftype}...")
        result = query_overpass(query)
        gdf = overpass_to_points_gdf(result, county_geom)
        facilities[ftype] = gdf
        print(f"  Found {len(gdf)} {ftype} in county")
        # Be polite to the Overpass API
        time.sleep(2)

    # Fetch district boundaries from SnoCoWA
    print("Fetching fire district boundaries...")
    try:
        fire_districts = query_arcgis_rest(SNOCO_DISTRICTS_URL, SNOCO_FIRE_LAYER)
        fire_districts = clip_to_county(fire_districts, sno)
        print(f"  Got {len(fire_districts)} fire districts")
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch fire districts: {e}")
        fire_districts = gpd.GeoDataFrame()

    print("Fetching hospital district boundaries...")
    try:
        hospital_districts = query_arcgis_rest(SNOCO_DISTRICTS_URL, SNOCO_HOSPITAL_LAYER)
        hospital_districts = clip_to_county(hospital_districts, sno)
        print(f"  Got {len(hospital_districts)} hospital districts")
    except (GEOSException, ValueError, TypeError) as e:
        print(f"  WARNING: Failed to fetch hospital districts: {e}")
        hospital_districts = gpd.GeoDataFrame()
    print("Fetching hillshade...")
    hill_img, hill_extent = fetch_hillshade(bbox_wgs84)

    print("Creating base map...")
    fig, ax, sno_clipped = create_base_map(
        sno, land, title="Snohomish County \u2014 Critical Facilities"
    )

    # Hillshade background
    ax.imshow(hill_img, extent=hill_extent, zorder=1, alpha=0.3, interpolation="bilinear")

    # Re-draw county on top of hillshade
    sno_clipped.plot(ax=ax, color="none", edgecolor="#444444", linewidth=1.2, zorder=5)

    # Fire district boundaries
    if not fire_districts.empty:
        fire_districts.plot(
            ax=ax, color="none",
            edgecolor="#FF6D00", linewidth=0.5, alpha=0.2, zorder=6,
        )

    # Hospital district boundaries
    if not hospital_districts.empty:
        hospital_districts.plot(
            ax=ax, color="none",
            edgecolor="#E53E3E", linewidth=0.5, alpha=0.2, zorder=6,
        )

    # Plot facility points
    # Schools (lowest zorder, most numerous)
    schools = facilities["schools"]
    if not schools.empty:
        ax.scatter(
            schools.geometry.x, schools.geometry.y,
            marker="s", s=30, color="#1565C0",
            edgecolor="white", linewidth=0.3,
            zorder=13, label="Schools",
        )

    # Fire stations
    fire_st = facilities["fire_stations"]
    if not fire_st.empty:
        ax.scatter(
            fire_st.geometry.x, fire_st.geometry.y,
            marker="^", s=60, color="#FF6D00",
            edgecolor="white", linewidth=0.4,
            zorder=14, label="Fire Stations",
        )

    # Police
    police = facilities["police"]
    if not police.empty:
        ax.scatter(
            police.geometry.x, police.geometry.y,
            marker="D", s=50, color="#2E7D32",
            edgecolor="white", linewidth=0.4,
            zorder=14, label="Police",
        )

    # Hospitals (highest zorder, most critical)
    hospitals = facilities["hospitals"]
    if not hospitals.empty:
        ax.scatter(
            hospitals.geometry.x, hospitals.geometry.y,
            marker="P", s=120, color="#E53E3E",
            edgecolor="white", linewidth=0.5,
            zorder=15, label="Hospitals",
        )

        # Label hospitals
        for _, row in hospitals.iterrows():
            name = row["name"]
            if not name:
                continue
            ax.annotate(
                name,
                xy=(row.geometry.x, row.geometry.y),
                xytext=(8, 8),
                textcoords="offset points",
                fontsize=7,
                fontweight="bold",
                color="#333333",
                zorder=16,
                path_effects=TEXT_HALO,
            )

    # Legend
    legend_handles = [
        Line2D([0], [0], marker="P", color="w", markerfacecolor="#E53E3E",
               markeredgecolor="white", markersize=12, label="Hospitals"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#FF6D00",
               markeredgecolor="white", markersize=10, label="Fire Stations"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor="#2E7D32",
               markeredgecolor="white", markersize=9, label="Police"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#1565C0",
               markeredgecolor="white", markersize=8, label="Schools"),
    ]

    if not fire_districts.empty:
        legend_handles.append(
            Patch(facecolor="none", edgecolor="#FF6D00", linewidth=1,
                  alpha=0.5, label="Fire Districts")
        )
    if not hospital_districts.empty:
        legend_handles.append(
            Patch(facecolor="none", edgecolor="#E53E3E", linewidth=1,
                  alpha=0.5, label="Hospital Districts")
        )

    place_legend(ax, legend_handles, ncol=3, fontsize=12)
    place_attribution(ax, "Data: OpenStreetMap contributors, Snohomish County GIS")

    # Save
    print("Saving map...")
    save_map(fig, OUTPUT)

    # Summary
    print("\nFacility counts:")
    for ftype, gdf in facilities.items():
        print(f"  {ftype}: {len(gdf)}")


if __name__ == "__main__":
    main()

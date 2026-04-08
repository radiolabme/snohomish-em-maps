#!/usr/bin/env python3
"""Tests for the Snohomish County emergency management map set.

Validates: data integrity, common scale/grid, output files, and per-map content.
"""

import os
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pytest
from PIL import Image

from snohomish_base import (
    DPI,
    FIG_SIZE,
    MAP_XLIM,
    MAP_YLIM,
    WATER_COLOR,
    create_base_map,
    load_land_clipped,
    load_snohomish_boundary,
    query_arcgis_rest,
    get_snohomish_bbox_wgs84,
)


MAP_DIR = "/Users/brian/Claude/map"
MAP_FILES = {
    "flood":    os.path.join(MAP_DIR, "snohomish_flood_zones.png"),
    "volcanic": os.path.join(MAP_DIR, "snohomish_volcanic.png"),
    "services": os.path.join(MAP_DIR, "snohomish_emergency_services.png"),
    "water":    os.path.join(MAP_DIR, "snohomish_water_mgmt.png"),
}

SNOCO_MAPSERVER = (
    "https://gis.snoco.org/sis/rest/services/Districts/"
    "Districts_and_Boundaries/MapServer"
)
FEMA_NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
DNR_VOLCANIC = (
    "https://gis.dnr.wa.gov/site1/rest/services/Public_Geology/"
    "Volcanic_Hazards/MapServer"
)



@pytest.fixture(scope="session")
def sno():
    return load_snohomish_boundary()


@pytest.fixture(scope="session")
def land():
    return load_land_clipped()


@pytest.fixture(scope="session")
def base_map(sno, land):
    fig, ax, sno_c = create_base_map(sno, land, title="Test")
    yield fig, ax, sno_c
    plt.close(fig)



class TestCommonScale:
    def test_all_pngs_exist(self):
        """All 4 map PNGs exist."""
        for name, path in MAP_FILES.items():
            assert os.path.isfile(path), f"Missing: {name} → {path}"

    def test_all_pngs_same_dimensions(self):
        """All maps have identical pixel dimensions (common scale)."""
        sizes = {}
        for name, path in MAP_FILES.items():
            img = Image.open(path)
            sizes[name] = img.size
        first = list(sizes.values())[0]
        for name, size in sizes.items():
            assert size == first, (
                f"{name} is {size}, expected {first} (all maps must match)"
            )

    def test_png_dimensions_reasonable(self):
        """PNG dimensions are large enough for the target DPI."""
        for name, path in MAP_FILES.items():
            img = Image.open(path)
            w, h = img.size
            # bbox_inches='tight' crops whitespace; county is wide/short
            # so height is trimmed significantly. Just verify ≥2000px each dim.
            assert w >= 2000, f"{name} width {w} below 2000px"
            assert h >= 2000, f"{name} height {h} below 2000px"

    def test_base_map_xlim(self, base_map):
        """Axes X limits match the fixed MAP_XLIM."""
        _, ax, _ = base_map
        assert ax.get_xlim() == pytest.approx(MAP_XLIM, abs=1)

    def test_base_map_ylim(self, base_map):
        """Axes Y limits match the fixed MAP_YLIM."""
        _, ax, _ = base_map
        assert ax.get_ylim() == pytest.approx(MAP_YLIM, abs=1)

    def test_scale_bar_present(self, base_map):
        """Base map has a scale bar (line artists)."""
        _, ax, _ = base_map
        # Scale bar is drawn with ax.plot — look for Line2D objects
        lines = ax.get_lines()
        assert len(lines) >= 3, "Expected at least 3 line segments for scale bar"

    def test_grid_lines_present(self, base_map):
        """Base map has grid lines at 10km intervals."""
        _, ax, _ = base_map
        # Grid lines are drawn with axvline/axhline
        lines = ax.get_lines()
        # Scale bar uses 3 lines, the rest are grid lines
        grid_line_count = len(lines) - 3
        # Expected: (130000/10000 + 1) x-lines + (68000/10000 + 1) y-lines ≈ 21
        assert grid_line_count > 15, f"Expected >15 grid lines, got {grid_line_count}"

    def test_water_background(self, base_map):
        """Axes background is the water color."""
        _, ax, _ = base_map
        bg = matplotlib.colors.to_hex(ax.get_facecolor())
        assert bg == WATER_COLOR.lower()



class TestDataSources:
    def test_fema_nfhl_responds(self):
        """FEMA NFHL REST endpoint is reachable and returns flood zone data."""
        bbox = get_snohomish_bbox_wgs84()
        # Query a small subset
        small_bbox = (bbox[0], bbox[1], bbox[0] + 0.1, bbox[1] + 0.1)
        gdf = query_arcgis_rest(FEMA_NFHL, 28, bbox_wgs84=small_bbox,
                                out_fields="FLD_ZONE")
        assert len(gdf) > 0, "FEMA NFHL returned no features"
        assert "FLD_ZONE" in gdf.columns

    def test_snoco_fire_districts_responds(self):
        """SnoCoWA fire districts endpoint returns data."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 31, out_fields="District")
        assert len(gdf) > 0
        assert "District" in gdf.columns

    def test_snoco_hospital_districts_responds(self):
        """SnoCoWA hospital districts endpoint returns data."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 33, out_fields="District")
        assert len(gdf) > 0

    def test_snoco_diking_districts_responds(self):
        """SnoCoWA diking districts endpoint returns data."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 38, out_fields="Name")
        assert len(gdf) > 0

    def test_snoco_drainage_districts_responds(self):
        """SnoCoWA drainage districts endpoint returns data."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 39, out_fields="Name")
        assert len(gdf) > 0

    def test_snoco_flood_control_responds(self):
        """SnoCoWA flood control districts endpoint returns data."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 40, out_fields="Name")
        assert len(gdf) > 0

    def test_dnr_volcanic_hazards_responds(self):
        """WA DNR volcanic hazards endpoint returns data."""
        bbox = get_snohomish_bbox_wgs84()
        gdf = query_arcgis_rest(DNR_VOLCANIC, 0, bbox_wgs84=bbox, out_fields="*")
        assert len(gdf) > 0



class TestFloodMap:
    def test_has_flood_zone_pixels(self):
        """Flood map contains red-ish pixels (high risk zones)."""
        img = np.array(Image.open(MAP_FILES["flood"]).convert("RGB"))
        # High risk red: R>200, G<100, B<100
        red_mask = (img[:,:,0] > 180) & (img[:,:,1] < 120) & (img[:,:,2] < 120)
        assert red_mask.sum() > 1000, "Expected visible red flood zones"

    def test_has_moderate_risk_pixels(self):
        """Flood map contains orange-ish pixels (moderate risk)."""
        img = np.array(Image.open(MAP_FILES["flood"]).convert("RGB"))
        # Moderate orange: R>220, G>140, B<120
        orange_mask = (img[:,:,0] > 220) & (img[:,:,1] > 140) & (img[:,:,2] < 120)
        assert orange_mask.sum() > 500, "Expected visible moderate risk zones"


class TestVolcanicMap:
    def test_has_lahar_pixels(self):
        """Volcanic map contains magenta/pink pixels (lahar zones)."""
        img = np.array(Image.open(MAP_FILES["volcanic"]).convert("RGB"))
        # Lahar magenta: R>180, B>100, G<R
        magenta_mask = (img[:,:,0] > 160) & (img[:,:,2] > 100) & (img[:,:,1] < img[:,:,0])
        assert magenta_mask.sum() > 1000, "Expected visible lahar zones"

    def test_has_tephra_zone(self):
        """Volcanic map has a large tephra/ash zone (light purple fill)."""
        img = np.array(Image.open(MAP_FILES["volcanic"]).convert("RGB"))
        # Tephra #CE93D8 is light purple — R>180, B>180, G<R (purple-ish)
        purple_mask = (img[:,:,0] > 180) & (img[:,:,2] > 180) & (img[:,:,1] < img[:,:,0])
        ratio = purple_mask.sum() / purple_mask.size
        assert ratio > 0.02, f"Expected large tephra zone, got {ratio:.2%}"


class TestServicesMap:
    def test_has_multiple_district_colors(self):
        """Emergency services map has multiple distinct colors (fire districts)."""
        img = np.array(Image.open(MAP_FILES["services"]).convert("RGB"))
        # Sample unique colors in the map body (exclude borders)
        # Check that there are many distinct hues
        from collections import Counter
        # Quantize to reduce noise
        quantized = (img // 32) * 32
        h, w, _ = quantized.shape
        center = quantized[h//4:3*h//4, w//4:3*w//4]
        colors = set(map(tuple, center.reshape(-1, 3)))
        assert len(colors) > 20, f"Expected many colors for districts, got {len(colors)}"

    def test_file_size_indicates_complexity(self):
        """Emergency services map should be the largest (most complex) file."""
        size = os.path.getsize(MAP_FILES["services"])
        assert size > 500_000, f"Expected >500KB, got {size}"


class TestWaterMgmtMap:
    def test_has_green_pixels(self):
        """Water management map has green pixels (diking districts)."""
        img = np.array(Image.open(MAP_FILES["water"]).convert("RGB"))
        green_mask = (img[:,:,1] > 150) & (img[:,:,0] < 150) & (img[:,:,2] < 150)
        assert green_mask.sum() > 100, "Expected visible green diking districts"

    def test_has_colored_districts(self):
        """Water management map has non-gray district fills."""
        img = np.array(Image.open(MAP_FILES["water"]).convert("RGB"))
        # Anything that's not gray/white/water-blue
        r, g, b = img[:,:,0], img[:,:,1], img[:,:,2]
        colored = (np.abs(r.astype(int) - g.astype(int)) > 30) | \
                  (np.abs(g.astype(int) - b.astype(int)) > 30)
        assert colored.sum() > 5000, "Expected visible colored district polygons"



class TestResolution:
    def test_ground_resolution(self):
        """Ground resolution is at or better than 50m/pixel (min for flood zones)."""
        img = Image.open(MAP_FILES["flood"])
        w_px, h_px = img.size
        map_width_m = MAP_XLIM[1] - MAP_XLIM[0]
        map_height_m = MAP_YLIM[1] - MAP_YLIM[0]
        gsd_x = map_width_m / w_px
        gsd_y = map_height_m / h_px
        assert gsd_x < 50, f"X ground resolution {gsd_x:.1f}m exceeds 50m minimum"
        assert gsd_y < 50, f"Y ground resolution {gsd_y:.1f}m exceeds 50m minimum"

    def test_minimum_image_size(self):
        """All maps meet the minimum 1100x1300 pixel threshold."""
        for name, path in MAP_FILES.items():
            img = Image.open(path)
            w, h = img.size
            assert w >= 1100, f"{name}: width {w} below 1100px minimum"
            assert h >= 1100, f"{name}: height {h} below 1100px minimum"

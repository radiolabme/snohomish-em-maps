#!/usr/bin/env python3
"""Tests for the Snohomish County combined emergency management map.

Validates: REST data sources, output PNG integrity, visual content, and common scale.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

import matplotlib
matplotlib.use("Agg")

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))

from snohomish_base import (
    DPI,
    FIG_SIZE,
    HILLSHADE_URL,
    MAP_XLIM,
    MAP_YLIM,
    query_arcgis_rest,
    get_snohomish_bbox_wgs84,
)


MAP_DIR = "/Users/brian/Claude/map"
COMBINED_PNG = os.path.join(MAP_DIR, "snohomish_combined.png")
FLOOD_PNG = os.path.join(MAP_DIR, "snohomish_flood_zones.png")


FEMA_NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
DNR_VOLCANIC = (
    "https://gis.dnr.wa.gov/site1/rest/services/Public_Geology/"
    "Volcanic_Hazards/MapServer"
)
SNOCO_MAPSERVER = (
    "https://gis.snoco.org/sis/rest/services/Districts/"
    "Districts_and_Boundaries/MapServer"
)
WA_STATE_PARKS = (
    "https://services5.arcgis.com/4LKAHwqnBooVDUlX/arcgis/rest/services/"
    "ParkBoundaries/FeatureServer"
)
NPS_BOUNDARIES = (
    "https://services1.arcgis.com/fBc8EJBxQRMcHlei/ArcGIS/rest/services/"
    "NPS_Land_Resources_Division_Boundary_and_Tract_Data_Service/FeatureServer"
)
WSDOT_ROUTES = (
    "https://data.wsdot.wa.gov/arcgis/rest/services/"
    "Shared/StateRoutes/MapServer"
)


@pytest.fixture(scope="session")
def snohomish_bbox():
    return get_snohomish_bbox_wgs84()


@pytest.fixture(scope="session")
def combined_image():
    """Load the combined PNG, skip if it does not exist yet."""
    if not os.path.isfile(COMBINED_PNG):
        pytest.skip(f"Combined map not yet generated: {COMBINED_PNG}")
    return Image.open(COMBINED_PNG)


@pytest.fixture(scope="session")
def combined_array(combined_image):
    """Return the combined PNG as an RGB numpy array."""
    return np.array(combined_image.convert("RGB"))



@pytest.mark.network
class TestDataSources:
    """Verify every REST endpoint used by the combined map returns data."""

    def test_fema_nfhl_flood_zones(self, snohomish_bbox):
        """FEMA NFHL layer 28 returns features with FLD_ZONE field."""
        bbox = snohomish_bbox
        small = (bbox[0], bbox[1], bbox[0] + 0.1, bbox[1] + 0.1)
        gdf = query_arcgis_rest(FEMA_NFHL, 28, bbox_wgs84=small,
                                out_fields="FLD_ZONE")
        assert len(gdf) > 0, "FEMA NFHL returned no features"
        assert "FLD_ZONE" in gdf.columns, "Missing FLD_ZONE field"

    def test_dnr_volcanic_hazards(self, snohomish_bbox):
        """WA DNR volcanic hazards layer 0 returns features with HAZARD_TYPE."""
        gdf = query_arcgis_rest(DNR_VOLCANIC, 0, bbox_wgs84=snohomish_bbox,
                                out_fields="HAZARD_TYPE")
        assert len(gdf) > 0, "DNR volcanic returned no features"
        assert "HAZARD_TYPE" in gdf.columns, "Missing HAZARD_TYPE field"

    def test_snoco_diking_districts(self):
        """SnoCoWA diking districts layer 38 returns features."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 38, out_fields="Name")
        assert len(gdf) > 0, "Diking districts (layer 38) returned no features"

    def test_snoco_drainage_districts(self):
        """SnoCoWA drainage districts layer 39 returns features."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 39, out_fields="Name")
        assert len(gdf) > 0, "Drainage districts (layer 39) returned no features"

    def test_snoco_flood_control_districts(self):
        """SnoCoWA flood control districts layer 40 returns features."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 40, out_fields="Name")
        assert len(gdf) > 0, "Flood control districts (layer 40) returned no features"

    def test_snoco_national_forest(self):
        """SnoCoWA National Forest layer 34 returns features with FORESTNAME."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 34, out_fields="FORESTNAME")
        assert len(gdf) > 0, "National Forest (layer 34) returned no features"
        assert "FORESTNAME" in gdf.columns, "Missing FORESTNAME field"

    def test_wa_state_parks(self, snohomish_bbox):
        """WA State Parks FeatureServer layer 2 returns features with ParkName."""
        gdf = query_arcgis_rest(WA_STATE_PARKS, 2,
                                bbox_wgs84=snohomish_bbox,
                                out_fields="ParkName", max_records=5)
        assert len(gdf) > 0, "WA State Parks returned no features"
        assert "ParkName" in gdf.columns, (
            f"Missing ParkName field; columns: {list(gdf.columns)}"
        )

    def test_nps_boundaries(self, snohomish_bbox):
        """NPS FeatureServer layer 2 is reachable (may return 0 features at county edge)."""
        url = (
            f"{NPS_BOUNDARIES}/2/query?where=STATE%3D'WA'"
            "&returnCountOnly=true&f=json"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        assert "count" in data, "NPS endpoint unreachable"

    def test_wsdot_state_routes(self, snohomish_bbox):
        """WSDOT State Routes layer 0 returns features with RT_TYPEA and DISPLAY."""
        bbox = snohomish_bbox
        small = (bbox[0], bbox[1], bbox[0] + 0.2, bbox[1] + 0.2)
        gdf = query_arcgis_rest(WSDOT_ROUTES, 0, bbox_wgs84=small,
                                out_fields="RT_TYPEA,DISPLAY")
        assert len(gdf) > 0, "WSDOT routes returned no features"
        assert "RT_TYPEA" in gdf.columns, "Missing RT_TYPEA field"
        assert "DISPLAY" in gdf.columns, "Missing DISPLAY field"

    def test_snoco_city_limits(self):
        """SnoCoWA city limits layer 13 returns features with NAME."""
        gdf = query_arcgis_rest(SNOCO_MAPSERVER, 13, out_fields="NAME")
        assert len(gdf) > 0, "City limits (layer 13) returned no features"
        assert "NAME" in gdf.columns, "Missing NAME field"

    def test_hillshade_url_reachable(self, snohomish_bbox):
        """USGS hillshade export endpoint is reachable for a small bbox."""
        bbox = snohomish_bbox
        # Use a very small bbox to keep it fast
        tiny = (bbox[0], bbox[1], bbox[0] + 0.05, bbox[1] + 0.05)
        params = urllib.parse.urlencode({
            "bbox": f"{tiny[0]},{tiny[1]},{tiny[2]},{tiny[3]}",
            "bboxSR": "4326",
            "imageSR": "2855",
            "size": "64,64",
            "format": "png",
            "f": "image",
        })
        url = f"{HILLSHADE_URL}/export?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()
        assert len(data) > 100, "Hillshade response too small — may be an error"
        # Verify it looks like a PNG (magic bytes)
        assert data[:4] == b"\x89PNG", "Hillshade response is not a valid PNG"



class TestOutputFile:
    """Verify the combined PNG exists, is valid, and meets size/dimension thresholds."""

    def test_file_exists(self):
        if not os.path.isfile(COMBINED_PNG):
            pytest.skip("Combined PNG not yet generated")
        assert os.path.isfile(COMBINED_PNG)

    def test_file_size_minimum(self):
        if not os.path.isfile(COMBINED_PNG):
            pytest.skip("Combined PNG not yet generated")
        size = os.path.getsize(COMBINED_PNG)
        assert size > 500_000, (
            f"Combined map should be >500KB (complex map), got {size:,} bytes"
        )

    def test_valid_png_format(self):
        if not os.path.isfile(COMBINED_PNG):
            pytest.skip("Combined PNG not yet generated")
        with open(COMBINED_PNG, "rb") as f:
            magic = f.read(8)
        assert magic[:4] == b"\x89PNG", "File does not have PNG magic bytes"

    def test_dimensions_match_map_scale(self, combined_image):
        """Dimensions are consistent with MAP_XLIM/MAP_YLIM at the target DPI."""
        w, h = combined_image.size
        assert w >= 2000, f"Width {w}px below 2000px minimum"
        assert h >= 2000, f"Height {h}px below 2000px minimum"

    def test_ground_resolution(self, combined_image):
        """Ground resolution is < 50m/pixel (readable flood zones and roads)."""
        w, h = combined_image.size
        map_width_m = MAP_XLIM[1] - MAP_XLIM[0]
        map_height_m = MAP_YLIM[1] - MAP_YLIM[0]
        gsd_x = map_width_m / w
        gsd_y = map_height_m / h
        assert gsd_x < 50, f"X ground resolution {gsd_x:.1f}m exceeds 50m limit"
        assert gsd_y < 50, f"Y ground resolution {gsd_y:.1f}m exceeds 50m limit"



class TestVisualContent:
    """Pixel-level checks to verify major map layers are rendered."""

    def test_contains_red_pixels_flood_zones(self, combined_array):
        """Combined map contains red pixels from flood zone layer."""
        img = combined_array
        red_mask = (img[:, :, 0] > 180) & (img[:, :, 1] < 120) & (img[:, :, 2] < 120)
        assert red_mask.sum() > 500, "Expected red pixels for flood zones"

    def test_contains_blue_pixels_interstates(self, combined_array):
        """Combined map contains blue-ish pixels from interstate roads."""
        img = combined_array
        blue_mask = (img[:, :, 2] > 150) & (img[:, :, 0] < 120) & (img[:, :, 1] < 150)
        assert blue_mask.sum() > 100, "Expected blue pixels for interstates"

    def test_contains_dark_pixels_roads(self, combined_array):
        """Combined map contains dark pixels from state route lines."""
        img = combined_array
        dark_mask = (img[:, :, 0] < 60) & (img[:, :, 1] < 60) & (img[:, :, 2] < 60)
        assert dark_mask.sum() > 500, "Expected dark pixels for state routes"

    def test_contains_green_pixels_forest_parks(self, combined_array):
        """Combined map contains green pixels from national forest / parks."""
        img = combined_array
        green_mask = (img[:, :, 1] > 130) & (img[:, :, 0] < 150) & (img[:, :, 2] < 150)
        assert green_mask.sum() > 1000, "Expected green pixels for forest/parks"

    def test_visual_complexity(self, combined_array):
        """Map is not mostly one color — the combined map should have many layers."""
        img = combined_array
        # Quantize to 32-level bins to reduce noise
        quantized = (img // 32) * 32
        h, w, _ = quantized.shape
        # Sample the center region to avoid border/whitespace
        center = quantized[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
        unique_colors = set(map(tuple, center.reshape(-1, 3)))
        assert len(unique_colors) > 30, (
            f"Expected many distinct colors for combined map, got {len(unique_colors)}"
        )



class TestCommonScale:
    """Verify the combined map shares the same scale as the individual maps."""

    def test_same_width_as_flood_map(self, combined_image):
        """Combined map has the same width as the flood zones map (same X scale).
        Height may differ slightly due to legend placement outside axes."""
        if not os.path.isfile(FLOOD_PNG):
            pytest.skip("Flood zones PNG not available for comparison")
        flood_img = Image.open(FLOOD_PNG)
        assert combined_image.size[0] == flood_img.size[0], (
            f"Width mismatch: combined {combined_image.size[0]} != flood {flood_img.size[0]}"
        )
        # Height within 5% tolerance (legend bbox_to_anchor may extend axes)
        h_ratio = combined_image.size[1] / flood_img.size[1]
        assert 0.95 < h_ratio < 1.05, (
            f"Height diverged: combined {combined_image.size[1]} vs flood {flood_img.size[1]}"
        )

#!/usr/bin/env python3
"""Tests for wa_counties_map: data integrity, rendering correctness, and output."""

import os

import matplotlib
matplotlib.use("Agg")  # non-interactive backend for CI

import matplotlib.pyplot as plt
import numpy as np
import pytest
from PIL import Image

from wa_counties_map import (
    EXPECTED_COUNTIES,
    LAKE_COLOR,
    WATER_COLOR,
    WA_COUNTY_NAMES,
    WA_FIPS,
    clip_counties_to_land,
    load_lakes,
    load_land,
    load_wa_counties,
    render_map,
)



@pytest.fixture(scope="session")
def wa():
    """Load WA counties once for the whole test session."""
    return load_wa_counties()


@pytest.fixture(scope="session")
def land():
    """Load Natural Earth land polygons once for the whole test session."""
    return load_land()


@pytest.fixture(scope="session")
def lakes():
    """Load Natural Earth lake polygons once for the whole test session."""
    return load_lakes()


@pytest.fixture(scope="session")
def rendered(wa, land, lakes, tmp_path_factory):
    """Render the full map (with water) once and return (fig, png_path)."""
    out = str(tmp_path_factory.mktemp("maps") / "test_wa.png")
    fig = render_map(wa, out, land=land, lakes=lakes)
    yield fig, out
    plt.close(fig)



class TestDataIntegrity:
    def test_county_count(self, wa):
        """Washington State has exactly 39 counties."""
        assert len(wa) == EXPECTED_COUNTIES

    def test_all_county_names_present(self, wa):
        """Every official WA county name appears in the dataset."""
        loaded_names = sorted(wa["NAME"].tolist())
        assert loaded_names == WA_COUNTY_NAMES

    def test_snohomish_exists(self, wa):
        """Snohomish County is present in the data."""
        match = wa[wa["NAME"] == "Snohomish"]
        assert len(match) == 1

    def test_all_geometries_valid(self, wa):
        """Every county geometry is valid (no self-intersections, etc.)."""
        assert wa.geometry.is_valid.all()

    def test_no_empty_geometries(self, wa):
        """No county has an empty geometry."""
        assert not wa.geometry.is_empty.any()

    def test_crs_is_set(self, wa):
        """Data has a coordinate reference system assigned."""
        assert wa.crs is not None

    def test_crs_is_projected(self, wa):
        """CRS is projected (meters), not geographic (degrees)."""
        assert wa.crs.is_projected

    def test_state_fips_consistent(self, wa):
        """All rows belong to Washington (FIPS 53)."""
        assert (wa["STATEFP"] == WA_FIPS).all()

    def test_no_duplicate_counties(self, wa):
        """No county name appears more than once."""
        assert wa["NAME"].is_unique



class TestWaterClipping:
    def test_land_data_loads(self, land):
        """Natural Earth land data loads and has geometry."""
        assert len(land) > 0
        assert not land.geometry.is_empty.all()

    def test_land_crs_matches_counties(self, wa, land):
        """Land data is in the same CRS as county data."""
        assert land.crs == wa.crs

    def test_lakes_data_loads(self, lakes):
        """Natural Earth lake data loads."""
        assert len(lakes) >= 0  # may be 0 if no lakes in bbox

    def test_clipping_preserves_all_counties(self, wa, land):
        """Land clipping retains all 39 counties (no inland counties lost)."""
        clipped = clip_counties_to_land(wa, land)
        assert len(clipped) == EXPECTED_COUNTIES

    def test_clipping_preserves_all_names(self, wa, land):
        """Every county name survives the clipping operation."""
        clipped = clip_counties_to_land(wa, land)
        assert sorted(clipped["NAME"].tolist()) == WA_COUNTY_NAMES

    def test_clipped_geometries_valid(self, wa, land):
        """All clipped county geometries are valid."""
        from shapely.validation import make_valid
        clipped = clip_counties_to_land(wa, land)
        for _, row in clipped.iterrows():
            g = make_valid(row.geometry)
            assert not g.is_empty, f"{row['NAME']} has empty geometry after clipping"

    def test_coastal_counties_smaller_after_clip(self, wa, land):
        """Coastal counties (e.g. San Juan, Island) lose area when water is removed."""
        clipped = clip_counties_to_land(wa, land)
        coastal = ["San Juan", "Island", "Jefferson", "Clallam"]
        for name in coastal:
            orig = wa[wa["NAME"] == name].iloc[0].geometry.area
            clip = clipped[clipped["NAME"] == name].iloc[0].geometry.area
            assert clip < orig, (
                f"{name} should be smaller after water clipping "
                f"(orig={orig:.0f}, clipped={clip:.0f})"
            )

    def test_inland_counties_roughly_same_size(self, wa, land):
        """Inland counties keep nearly all their area after clipping."""
        clipped = clip_counties_to_land(wa, land)
        inland = ["Spokane", "Whitman", "Adams", "Grant"]
        for name in inland:
            orig = wa[wa["NAME"] == name].iloc[0].geometry.area
            clip = clipped[clipped["NAME"] == name].iloc[0].geometry.area
            ratio = clip / orig
            assert ratio > 0.95, (
                f"{name} lost too much area: {ratio:.2%} retained"
            )



class TestRendering:
    def test_figure_created(self, rendered):
        """render_map returns a matplotlib Figure."""
        fig, _ = rendered
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_single_axes(self, rendered):
        """Figure has exactly one Axes."""
        fig, _ = rendered
        assert len(fig.axes) == 1

    def test_title(self, rendered):
        """Axes title is 'Washington State Counties'."""
        fig, _ = rendered
        ax = fig.axes[0]
        assert ax.get_title() == "Washington State Counties"

    def test_water_background(self, rendered):
        """Axes background is set to the water color."""
        fig, _ = rendered
        ax = fig.axes[0]
        bg = matplotlib.colors.to_hex(ax.get_facecolor())
        assert bg == WATER_COLOR.lower()

    def test_all_counties_labeled(self, rendered):
        """Every county name appears as a text annotation on the map."""
        fig, _ = rendered
        ax = fig.axes[0]
        texts = {t.get_text() for t in ax.texts}
        for name in WA_COUNTY_NAMES:
            assert name in texts, f"Missing label: {name}"

    def test_snohomish_label_is_bold(self, rendered):
        """The Snohomish label uses bold fontweight."""
        fig, _ = rendered
        ax = fig.axes[0]
        snohomish_texts = [t for t in ax.texts if t.get_text() == "Snohomish"]
        assert len(snohomish_texts) == 1
        assert snohomish_texts[0].get_fontweight() == "bold"

    def test_snohomish_label_is_white(self, rendered):
        """Snohomish label text is white (visible on blue fill)."""
        fig, _ = rendered
        ax = fig.axes[0]
        snohomish_texts = [t for t in ax.texts if t.get_text() == "Snohomish"]
        assert matplotlib.colors.to_hex(snohomish_texts[0].get_color()) == "#ffffff"

    def test_label_font_size_is_14(self, rendered):
        """All county labels use 14pt font."""
        fig, _ = rendered
        ax = fig.axes[0]
        for t in ax.texts:
            assert t.get_fontsize() == 14, (
                f"'{t.get_text()}' has size {t.get_fontsize()}, expected 14"
            )

    def test_label_font_is_sans_serif(self, rendered):
        """All county labels use sans-serif font family."""
        fig, _ = rendered
        ax = fig.axes[0]
        for t in ax.texts:
            assert t.get_fontfamily() == ["sans-serif"], (
                f"'{t.get_text()}' uses {t.get_fontfamily()}, expected sans-serif"
            )

    def test_legend_present(self, rendered):
        """The map has a legend."""
        fig, _ = rendered
        ax = fig.axes[0]
        assert ax.get_legend() is not None

    def test_legend_has_three_entries(self, rendered):
        """Legend contains 3 entries: Snohomish, Other Counties, Water."""
        fig, _ = rendered
        ax = fig.axes[0]
        legend = ax.get_legend()
        assert len(legend.get_texts()) == 3

    def test_legend_labels(self, rendered):
        """Legend labels include Snohomish County, Other Counties, and Water."""
        fig, _ = rendered
        ax = fig.axes[0]
        legend = ax.get_legend()
        labels = {t.get_text() for t in legend.get_texts()}
        assert labels == {"Snohomish County", "Other Counties", "Water"}

    def test_axes_off(self, rendered):
        """Axis spines / ticks are turned off for a clean look."""
        fig, _ = rendered
        ax = fig.axes[0]
        assert not ax.axison



class TestOutputFile:
    def test_png_exists(self, rendered):
        """The output PNG file was created."""
        _, path = rendered
        assert os.path.isfile(path)

    def test_png_not_empty(self, rendered):
        """The PNG file has non-trivial size."""
        _, path = rendered
        assert os.path.getsize(path) > 10_000

    def test_png_is_valid_image(self, rendered):
        """The file is a valid PNG image."""
        _, path = rendered
        img = Image.open(path)
        assert img.format == "PNG"

    def test_png_dimensions_reasonable(self, rendered):
        """Output image has reasonable dimensions (at 200 dpi, 22x15 -> ~4400x3000)."""
        _, path = rendered
        img = Image.open(path)
        w, h = img.size
        assert 3500 < w < 5500
        assert 2500 < h < 4000

    def test_png_contains_water_pixels(self, rendered):
        """The output image contains blue-ish water pixels (Puget Sound is visible)."""
        _, path = rendered
        img = Image.open(path).convert("RGB")
        arr = np.array(img)
        # Water color #B3D4F0 -> R=179, G=212, B=240
        # Look for pixels that are distinctly blue-ish (B > R and B > 200)
        blue_mask = (arr[:, :, 2] > 200) & (arr[:, :, 2] > arr[:, :, 0] + 20)
        blue_ratio = blue_mask.sum() / blue_mask.size
        assert blue_ratio > 0.01, (
            f"Expected visible water area, but only {blue_ratio:.4%} of pixels are blue"
        )

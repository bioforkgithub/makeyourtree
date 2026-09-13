# SPDX-License-Identifier: MIT
"""The output-format registry.

The point of this module is that the MIT core can offer PNG and PDF without
importing Qt, by discovering exporters through entry-point metadata. Two things
therefore have to hold and are checked here: SVG works with nothing installed,
and asking for a format whose provider is absent produces an instruction rather
than an ``ImportError`` traceback.
"""

from __future__ import annotations

import pytest

from makeyourtree.render import exporters
from makeyourtree.render.exporters import (BUILTIN_FORMATS, ExportError,
                                           UnavailableFormat,
                                           available_formats, export_scene,
                                           format_for_path, is_raster)
from makeyourtree.scene.compose import compose


@pytest.fixture
def scene(document):
    return compose(document)


@pytest.fixture(autouse=True)
def _restore_registry():
    """Each test may poke the cache; none may leak it to the next."""
    saved = exporters._cache
    yield
    exporters._cache = saved


# ------------------------------------------------------------- the registry


def test_svg_needs_no_optional_dependency():
    assert "svg" in BUILTIN_FORMATS
    assert "svg" in available_formats()


def test_available_formats_is_sorted_and_deduplicated():
    formats = available_formats()
    assert list(formats) == sorted(set(formats))


def test_only_png_is_raster():
    assert is_raster("png")
    assert not is_raster("svg")
    assert not is_raster("pdf")


def test_raster_check_is_case_insensitive():
    assert is_raster("PNG")


# ------------------------------------------------------ format from the path


@pytest.mark.parametrize("name,expected", [
    ("figure.svg", "svg"),
    ("figure.pdf", "pdf"),
    ("figure.png", "png"),
    ("FIGURE.PNG", "png"),
    ("figure.tree.svg", "svg"),
])
def test_the_extension_picks_the_format(name, expected):
    assert format_for_path(name) == expected


def test_an_unknown_extension_falls_back_rather_than_raising():
    """--output-format must be able to win over a misleading extension."""
    assert format_for_path("figure.dat") == "svg"
    assert format_for_path("figure.dat", default="png") == "png"


# ------------------------------------------------------------------ writing


def test_svg_export_writes_a_real_document(scene, tmp_path):
    path = tmp_path / "out.svg"
    export_scene(scene, path, "svg")
    text = path.read_text(encoding="utf-8")
    assert text.lstrip().startswith("<svg")
    assert "</svg>" in text


def test_svg_carries_physical_units(scene, tmp_path):
    """Without the unit an SVG imports 25% smaller than the same figure as PDF."""
    path = tmp_path / "out.svg"
    export_scene(scene, path, "svg")
    text = path.read_text(encoding="utf-8")
    assert 'width="' in text and 'pt" height="' in text
    assert 'viewBox="0 0 ' in text


def test_dpi_is_accepted_and_ignored_by_a_vector_format(scene, tmp_path):
    a, b = tmp_path / "a.svg", tmp_path / "b.svg"
    export_scene(scene, a, "svg", dpi=72)
    export_scene(scene, b, "svg", dpi=1200)
    assert a.read_bytes() == b.read_bytes()


def test_an_unknown_format_lists_what_is_available(scene, tmp_path):
    with pytest.raises(ExportError) as excinfo:
        export_scene(scene, tmp_path / "out.xyz", "xyz")
    assert "svg" in str(excinfo.value)


def test_a_missing_provider_says_how_to_install_it(scene, tmp_path, monkeypatch):
    """The message a user gets after `pip install makeyourtree` with no extra."""
    monkeypatch.setattr(exporters, "_cache", {"svg": exporters._export_svg})
    with pytest.raises(UnavailableFormat) as excinfo:
        export_scene(scene, tmp_path / "out.png", "png")
    message = str(excinfo.value)
    assert "studio" in message and "pip install" in message


def test_a_broken_entry_point_does_not_break_svg(monkeypatch):
    """A half-installed optional dependency must not take the core down."""
    class _Exploding:
        name = "png"

        def load(self):
            raise RuntimeError("no Qt here")

    monkeypatch.setattr(exporters, "_cache", None)
    monkeypatch.setattr(exporters, "entry_points", None, raising=False)
    monkeypatch.setattr("importlib.metadata.entry_points",
                        lambda **kw: [_Exploding()])
    assert "svg" in available_formats()
    assert "png" not in available_formats()

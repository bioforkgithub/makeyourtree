# SPDX-License-Identifier: MIT
"""The three exporters, checked on facts a file carries rather than on pixels.

The offscreen platform has no fonts, so glyph rendering is meaningless here.
What matters and what is asserted: the raster size is exactly what
:func:`png_size` predicts, the SVG bytes are the core renderer's bytes, and the
PDF is a real, vector PDF at the scene's own point size.
"""

from __future__ import annotations

import re
import zlib

import pytest
from PySide6.QtGui import QImage

from makeyourtree.render import render_svg
from makeyourtree.style.color import Color
from makeyourtree_studio.export.raster import (PDF_RESOLUTION, export_pdf,
                                           export_png, export_svg, png_size,
                                           resolve_background)

SCALES = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]

SIZES = [
    (320.0, 240.0),
    (92.22, 109.61),
    (1.0, 1.0),
    (1000.5, 37.25),
    (13.3333, 999.9999),
]


def _content_streams(data: bytes) -> list[bytes]:
    """Every Flate-compressed stream in a PDF, decompressed.

    Qt compresses the page content, so the drawing operators are only visible
    after inflation -- which is also how we tell a vector page from one holding
    a single embedded bitmap.
    """
    out: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        try:
            out.append(zlib.decompress(data[start:end]))
        except zlib.error:
            continue
    return out


# --------------------------------------------------------------------- PNG


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("size", SIZES)
def test_png_dimensions_match_the_prediction(qapp, tmp_path, size, scale):
    """The predicted size and the produced file must agree for every combination.

    This is the contract the export dialog's live label rests on.
    """
    from makeyourtree.scene.marks import Scene

    scene = Scene(width=size[0], height=size[1], background=Color(255, 255, 255))
    predicted = png_size(scene, scale)

    path = tmp_path / f"figure_{size[0]}_{scale}.png"
    export_png(scene, path, scale=scale)

    image = QImage(str(path))
    assert not image.isNull(), "exported PNG did not load back"
    assert (image.width(), image.height()) == predicted


def test_png_scale_is_linear(qapp, tmp_path, scene):
    """Doubling the scale doubles both dimensions, with no drift."""
    single = tmp_path / "one.png"
    double = tmp_path / "two.png"
    export_png(scene, single, scale=1.0)
    export_png(scene, double, scale=2.0)

    a, b = QImage(str(single)), QImage(str(double))
    assert (a.width(), a.height()) == (320, 240)
    assert (b.width(), b.height()) == (640, 480)


def test_png_honours_an_explicit_background(qapp, tmp_path, scene):
    """A named background overrides the theme's, corner pixel included."""
    path = tmp_path / "white.png"
    export_png(scene, path, scale=1.0, background="#ff0000")
    image = QImage(str(path))
    assert image.pixelColor(0, 0).getRgb()[:3] == (255, 0, 0)


def test_png_transparent_background_leaves_alpha_zero(qapp, tmp_path, scene):
    path = tmp_path / "clear.png"
    export_png(scene, path, scale=1.0, background="transparent")
    image = QImage(str(path))
    assert image.hasAlphaChannel()
    assert image.pixelColor(0, 0).alpha() == 0


def test_png_rejects_a_non_positive_scale(qapp, tmp_path, scene):
    with pytest.raises(ValueError):
        export_png(scene, tmp_path / "bad.png", scale=0.0)


def test_png_size_never_returns_zero():
    """A scene can legitimately be sub-pixel; a zero-sized QImage cannot exist."""
    from makeyourtree.scene.marks import Scene

    assert png_size(Scene(width=0.4, height=0.4), 1.0) == (1, 1)


def test_resolve_background_defaults_to_the_scene(scene):
    assert resolve_background(scene, None) is scene.background
    assert resolve_background(scene, "white") == Color(255, 255, 255)
    assert resolve_background(scene, Color(1, 2, 3, 4)) == Color(1, 2, 3, 4)
    with pytest.raises(TypeError):
        resolve_background(scene, 17)


# --------------------------------------------------------------------- SVG


def test_svg_export_is_byte_for_byte_the_core_renderer(tmp_path, scene):
    """The studio must add nothing of its own to the vector output.

    Any divergence here would mean the CLI and the application produce different
    files from the same document.
    """
    path = tmp_path / "figure.svg"
    export_svg(scene, path)
    assert path.read_bytes() == render_svg(scene).encode("utf-8")


def test_svg_export_records_the_scene_size(tmp_path, fractional_scene):
    path = tmp_path / "fractional.svg"
    export_svg(fractional_scene, path)
    text = path.read_text(encoding="utf-8")
    # The unit is part of the contract: it is what makes an SVG and a PDF of
    # the same scene the same physical size.
    assert 'width="92.22pt"' in text
    assert 'height="109.61pt"' in text
    assert 'viewBox="0 0 92.22 109.61"' in text


# --------------------------------------------------------------------- PDF


def test_pdf_is_a_real_pdf_of_non_trivial_size(qapp, tmp_path, scene):
    path = tmp_path / "figure.pdf"
    export_pdf(scene, path)
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 1000, "a PDF this small cannot contain the figure"
    assert data.rstrip().endswith(b"%%EOF")


def test_pdf_is_vector_not_an_embedded_bitmap(qapp, tmp_path, scene):
    """A rasterised PDF would defeat the purpose of offering PDF at all."""
    path = tmp_path / "vector.pdf"
    export_pdf(scene, path)
    data = path.read_bytes()

    assert b"/Subtype /Image" not in data
    assert b"/DCTDecode" not in data

    operators = b"".join(_content_streams(data))
    assert operators, "no readable content stream in the PDF"
    # `re` fills a rectangle, `m`/`l` move and line: the marks in the fixture.
    assert re.search(rb"\bre\b", operators)
    assert re.search(rb"\bl\b", operators)


def test_pdf_page_is_the_scene_at_72dpi(qapp, tmp_path, scene):
    """Resolution 72 makes one scene unit one PDF point, so a 320-unit figure
    is a 320-point page."""
    path = tmp_path / "page.pdf"
    export_pdf(scene, path)
    boxes = re.findall(rb"/MediaBox \[([^\]]*)\]", path.read_bytes())
    assert boxes, "no MediaBox in the PDF"
    x0, y0, x1, y1 = (float(v) for v in boxes[0].split())
    assert (x0, y0) == (0.0, 0.0)
    assert abs(x1 - scene.width) <= 1.0
    assert abs(y1 - scene.height) <= 1.0
    assert PDF_RESOLUTION == 72


def test_pdf_honours_an_explicit_page_size(qapp, tmp_path, scene):
    path = tmp_path / "sized.pdf"
    export_pdf(scene, path, size=(595.0, 842.0))
    boxes = re.findall(rb"/MediaBox \[([^\]]*)\]", path.read_bytes())
    x0, y0, x1, y1 = (float(v) for v in boxes[0].split())
    assert abs(x1 - 595.0) <= 1.0
    assert abs(y1 - 842.0) <= 1.0


def test_all_three_formats_consume_the_same_scene(qapp, tmp_path, scene):
    """Exporting three ways must not mutate the scene between calls."""
    before = (scene.width, scene.height, scene.count())
    export_svg(scene, tmp_path / "a.svg")
    export_png(scene, tmp_path / "a.png", scale=1.0, background="white")
    export_pdf(scene, tmp_path / "a.pdf")
    assert (scene.width, scene.height, scene.count()) == before
    assert scene.background == Color(250, 250, 252)


# --------------------------------------------------------- the drawing path


def test_a_complete_install_exports_through_the_canvas_backend():
    """File and screen must come off one implementation.

    ``raster`` tolerates the canvas package being absent so it can be used from
    headless tooling, but in a full installation the canvas backend is the path
    that must be taken -- otherwise an export could drift from the canvas.
    """
    from makeyourtree_studio.canvas.qt_backend import QtBackend
    from makeyourtree_studio.export.raster import _qt_backend_class

    assert _qt_backend_class() is QtBackend


def test_marks_actually_reach_the_pixels(qapp, tmp_path):
    """Guards against an export that writes a correctly sized blank page."""
    from makeyourtree.scene.marks import Paint, RectMark, Scene

    scene = Scene(width=40.0, height=40.0, background=Color(255, 255, 255))
    scene.add(RectMark(paint=Paint(fill=Color(0, 0, 255)),
                       x=10.0, y=10.0, w=20.0, h=20.0))

    path = tmp_path / "solid.png"
    export_png(scene, path, scale=1.0)
    image = QImage(str(path))

    assert image.pixelColor(20, 20).getRgb()[:3] == (0, 0, 255)
    assert image.pixelColor(2, 2).getRgb()[:3] == (255, 255, 255)

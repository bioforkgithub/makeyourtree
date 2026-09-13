# SPDX-License-Identifier: MIT
"""File export for a composed :class:`~makeyourtree.scene.marks.Scene`.

Every exporter here consumes the *same* ``Scene`` the canvas paints, so a file
can never show something the screen does not.  That is the whole reason
:mod:`makeyourtree.render` has a single scene walker: a second, export-only drawing
path is the classic way "looks right on screen, wrong in the paper figure" bugs
get in.

SVG is produced by the pure-Python writer in the core.  PNG and PDF go through
``QPainter``: PNG onto a ``QImage`` at a caller-chosen scale, PDF onto a
``QPdfWriter`` whose resolution is pinned to 72 dpi so one scene unit is exactly
one PostScript point and the result stays vector -- an embedded bitmap would
defeat the point of offering PDF at all.
"""

from __future__ import annotations

import dataclasses
import math
import os
import sys
from typing import Any

from PySide6.QtCore import QByteArray, QMarginsF, QRectF, QSizeF
from PySide6.QtGui import (QColor, QImage, QPageLayout, QPageSize, QPainter,
                           QPdfWriter)

from makeyourtree.render import render_svg
from makeyourtree.render.sizing import scale_for_dpi
from makeyourtree.render.backend import render
from makeyourtree.scene.marks import Scene
from makeyourtree.style.color import Color, parse_color

__all__ = ["export_svg", "export_png", "export_pdf", "png_size",
           "resolve_background", "PDF_RESOLUTION",
           "export_png_dpi", "export_pdf_dpi",
           "ensure_qt_application", "warn_if_fontless"]

PDF_RESOLUTION = 72
"""Device resolution for PDF output.  72 dpi makes scene units and PDF points
identical, so a figure measured in the studio keeps its size in a page-layout
program without a conversion step."""

_MIN_PIXELS = 1


# ---------------------------------------------------------------- geometry


def png_size(scene: Scene, scale: float = 2.0) -> tuple[int, int]:
    """Pixel dimensions :func:`export_png` will produce for *scene* at *scale*.

    The export dialog shows this to the user before the file exists, so the two
    must agree exactly; sharing one function is the only way to guarantee that.

    Rounds half up rather than taking the ceiling, because the dialog derives
    the scale from a requested pixel width (``scale = width / scene.width``) and
    a one-ULP round trip would otherwise silently add a pixel.
    """
    w = max(_MIN_PIXELS, int(math.floor(float(scene.width) * float(scale) + 0.5)))
    h = max(_MIN_PIXELS, int(math.floor(float(scene.height) * float(scale) + 0.5)))
    return w, h


def resolve_background(scene: Scene, background: Any) -> Color:
    """Pick the paper colour for a raster export.

    ``None`` means "whatever the theme says", which keeps an export consistent
    with the canvas by default.  A string goes through the core colour parser,
    so ``"transparent"``, ``"white"`` and ``"#112233"`` all work.
    """
    if background is None:
        return scene.background
    if isinstance(background, Color):
        return background
    if isinstance(background, str):
        return parse_color(background)
    raise TypeError("background must be a Color, a colour string or None, "
                    f"not {type(background).__name__}")


def _qcolor(color: Color) -> QColor:
    return QColor(color.r, color.g, color.b, color.a)


# ---------------------------------------------------------------- painting


def _qt_backend_class() -> type | None:
    """The canvas painter backend, or ``None`` when the canvas is unavailable.

    Deferred and optional so this module -- which is also the export path used
    by headless tooling -- does not hard-require the interactive canvas to be
    importable.
    """
    try:
        from ..canvas.qt_backend import QtBackend
    except ImportError:
        return None
    return QtBackend


def _paint_scene(painter: QPainter, scene: Scene) -> None:
    """Draw *scene* into *painter*, in scene units.

    The preferred path is the canvas's ``QtBackend``, so file and screen come
    off one implementation.  When it is unavailable the scene is routed through
    the core SVG writer and Qt's SVG renderer: still the same ``Scene``, still
    the same core scene walker, and still vector output, so the two paths agree
    on content even though they differ in machinery.
    """
    backend_cls = _qt_backend_class()
    if backend_cls is not None:
        render(scene, backend_cls(painter), include_overlay=False)
        return
    from PySide6.QtSvg import QSvgRenderer

    data = QByteArray(render_svg(scene).encode("utf-8"))
    QSvgRenderer(data).render(painter, QRectF(0.0, 0.0,
                                              float(scene.width),
                                              float(scene.height)))


# ----------------------------------------------------------------- exports


def export_svg(scene: Scene, path: str | os.PathLike[str]) -> None:
    """Write *scene* as SVG 1.1.

    Delegates wholesale to :func:`makeyourtree.render.render_svg`; no Qt is
    involved, which is what lets the identical export run from the CLI.  The
    file is opened with newline translation off so the bytes on disk are the
    renderer's bytes on every platform.
    """
    text = render_svg(scene)
    with open(os.fspath(path), "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def export_png(scene: Scene, path: str | os.PathLike[str], *,
               scale: float = 2.0, background: Any = None) -> None:
    """Rasterise *scene* to PNG at *scale* times its scene-unit size.

    The buffer is premultiplied ARGB so a transparent background composites
    correctly under antialiasing; Qt's encoder un-premultiplies on the way out.
    """
    if scale <= 0:
        raise ValueError(f"scale must be positive, got {scale!r}")
    bg = resolve_background(scene, background)
    painted = dataclasses.replace(scene, background=bg)
    width, height = png_size(painted, scale)

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull():
        raise MemoryError(f"could not allocate a {width}x{height} image")
    image.fill(_qcolor(bg))

    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.scale(float(scale), float(scale))
        _paint_scene(painter, painted)
    finally:
        painter.end()

    if not image.save(os.fspath(path), "PNG"):
        raise OSError(f"could not write PNG to {os.fspath(path)!r}")


def export_pdf(scene: Scene, path: str | os.PathLike[str], *,
               size: tuple[float, float] | None = None) -> None:
    """Write *scene* as a single-page vector PDF.

    *size* overrides the page size in points; by default the page is exactly
    the scene with zero margins, so nothing is cropped and nothing is padded.
    """
    width, height = size if size is not None else (scene.width, scene.height)
    width = max(1.0, float(width))
    height = max(1.0, float(height))

    writer = QPdfWriter(os.fspath(path))
    writer.setResolution(PDF_RESOLUTION)
    writer.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Unit.Point,
                                 "MakeYourTree",
                                 QPageSize.SizeMatchPolicy.ExactMatch))
    writer.setPageMargins(QMarginsF(0.0, 0.0, 0.0, 0.0), QPageLayout.Unit.Point)
    writer.setTitle(str(scene.metadata.get("title", "") or "MakeYourTree figure"))

    painter = QPainter(writer)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = scene.background
        if bg.a > 0:
            painter.fillRect(QRectF(0.0, 0.0, width, height), _qcolor(bg))
        _paint_scene(painter, scene)
    finally:
        painter.end()


# ----------------------------------------------------- registered exporters


_CLI_APP: Any = None
"""Kept alive deliberately. Qt aborts the process if its application object is
collected while a paint device still exists, and a module global is the only
lifetime long enough to cover a whole CLI run."""


def ensure_qt_application() -> Any:
    """Return a ``QGuiApplication``, creating one if the process has none.

    Qt requires an application instance before any paint device exists;
    ``QPdfWriter`` in particular aborts the process outright without one, which
    is how a CLI ``render figure.pdf`` used to exit 127 having written a
    zero-byte file. The CLI has no application of its own, so the exporters
    make one.

    ``QGuiApplication`` rather than ``QApplication``: rendering needs fonts and
    a paint stack, not widgets. If no display is available -- a CI job, an SSH
    session, a container -- Qt cannot start its normal platform plugin, so the
    offscreen plugin is used as a fallback.
    """
    global _CLI_APP
    from PySide6.QtGui import QGuiApplication

    existing = QGuiApplication.instance()
    if existing is not None:
        return existing
    try:
        _CLI_APP = QGuiApplication([])
    except Exception:
        # No display. Offscreen always starts, at the cost of the font warning
        # below on platforms whose offscreen plugin registers no families.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _CLI_APP = QGuiApplication([])
    return _CLI_APP


def warn_if_fontless(stream: Any = None) -> bool:
    """True when Qt has no font families, so text would rasterise as blank boxes.

    Worth saying out loud rather than shipping a figure whose every label is a
    row of tofu: the file looks plausible until someone opens it.
    """
    from PySide6.QtGui import QFontDatabase

    if QFontDatabase.families():
        return False
    print("warning: Qt reports no font families, so text will not render. "
          "On a headless machine, install fonts or run under xvfb-run.",
          file=stream or sys.stderr)
    return True


#
# These are what ``makeyourtree.render.exporters`` finds through the
# ``makeyourtree.exporters`` entry points declared in ``pyproject.toml``. They
# exist so the Qt-free CLI can offer PNG and PDF when the desktop extra is
# installed, without the core ever importing Qt. Each takes the keyword set the
# registry promises and ignores what does not apply to it -- ``dpi`` is
# meaningless for a vector format, and saying so here is cheaper than making
# every caller ask which format it has.


def export_png_dpi(scene: Scene, path: str | os.PathLike[str], *,
                   dpi: float = 300.0, background: Any = None,
                   title: str | None = None) -> None:
    """Rasterise at *dpi*, treating one scene unit as one point.

    The entry point for PNG. ``scale`` and ``dpi`` are two spellings of one
    number; :func:`makeyourtree.render.sizing.scale_for_dpi` owns the
    conversion so the CLI, the export dialog and this function cannot drift.
    """
    ensure_qt_application()
    warn_if_fontless()
    export_png(scene, path, scale=scale_for_dpi(dpi), background=background)


def export_pdf_dpi(scene: Scene, path: str | os.PathLike[str], *,
                   dpi: float = 72.0, background: Any = None,
                   title: str | None = None) -> None:
    """Write a vector PDF. *dpi* is accepted and ignored: PDF has no pixels."""
    ensure_qt_application()
    warn_if_fontless()
    painted = scene
    if background is not None:
        painted = dataclasses.replace(
            scene, background=resolve_background(scene, background))
    export_pdf(painted, path)

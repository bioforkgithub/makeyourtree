# SPDX-License-Identifier: MIT
"""Measure a published figure, without recognising it.

This is the provider behind :func:`makeyourtree.guide.figure.inspect_figure`.
It renders a PDF page or decodes an image with Qt, then answers a few questions
about the pixels with NumPy:

* **Is there a hole in the middle?**  A fan leaves its centre empty around the
  root, so ink density near the centroid falls at or below the average; a
  rectangle is densest exactly there.  Together with the aspect ratio -- a fan
  is square, a rectangular phylogram two to three times wider than tall -- that
  separates the two cleanly.  The thresholds were picked by measuring the
  gallery, not guessed: see the comment at the test itself, including the
  plausible-sounding measure that turned out to separate nothing.
* **How much saturated colour is there, and in how many distinct hues?**  A bare
  tree is nearly all grey ink.  Bands of saturated colour mean annotation, and
  a handful of well-separated hues means categories while a smooth run of one
  hue means a continuous scale.

Everything it reports is something it can point at.  It never claims to know
what the figure *is*, because it does not: two of these measurements together
suggest a circular layout with categorical rings, and that suggestion is offered
as a pre-filled answer the user can overrule, with the evidence beside it.

Deliberately conservative.  A wrong suggestion presented confidently is worse
than no suggestion, because the user came here precisely because they cannot
tell.  Thresholds are set so that ambiguous figures fall through to the
interview rather than being guessed at.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QImage

from makeyourtree.guide.figure import FigureError, FigureReading, Observation

__all__ = ["inspect_figure", "load_image", "analyse"]

#: Long edge the figure is scaled to before analysis. Large enough to keep thin
#: branch lines, small enough that the whole thing is a fraction of a second.
ANALYSIS_SIZE = 900

#: A pixel counts as "ink" when it is this much darker than the page.
_INK_THRESHOLD = 0.72

#: Saturation above which a pixel counts as deliberate colour rather than grey.
_COLOUR_THRESHOLD = 0.25


def _ensure_app() -> None:
    """Qt needs an application object before any image can be decoded."""
    if QGuiApplication.instance() is None:
        try:
            _ensure_app._app = QGuiApplication([])  # type: ignore[attr-defined]
        except Exception:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            _ensure_app._app = QGuiApplication([])  # type: ignore[attr-defined]


def _load_pdf(path: str) -> QImage:
    """Render the first page of a PDF.

    Qt PDF is LGPL-3.0 like the rest of Qt, not one of the GPL-only add-ons, so
    it is safe to link here; ``tests/test_licensing.py`` guards that list.
    """
    from PySide6.QtPdf import QPdfDocument

    document = QPdfDocument()
    status = document.load(path)
    if document.pageCount() < 1:
        raise FigureError(f"the PDF has no pages (loader said {status})")
    size = document.pagePointSize(0)
    scale = ANALYSIS_SIZE / max(1.0, max(size.width(), size.height()))
    target = QSize(max(1, int(size.width() * scale)),
                   max(1, int(size.height() * scale)))
    image = document.render(0, target)
    if image.isNull():
        raise FigureError("the first page of the PDF could not be rendered")
    return image


def load_image(path: str) -> QImage:
    """Decode *path* to an image, whatever kind of file it is."""
    _ensure_app()
    if os.path.splitext(path)[1].lower() == ".pdf":
        image = _load_pdf(path)
    else:
        image = QImage(path)
        if image.isNull():
            raise FigureError(
                "not an image this build can read. Supported: PDF, PNG, JPEG, "
                "BMP, TIFF and WebP.")
    if max(image.width(), image.height()) > ANALYSIS_SIZE:
        image = image.scaled(ANALYSIS_SIZE, ANALYSIS_SIZE,
                             aspectMode=1, mode=1)  # KeepAspectRatio, Smooth
    return image.convertToFormat(QImage.Format.Format_RGB888)


def _to_array(image: QImage) -> np.ndarray:
    """RGB float array in 0..1, shaped (height, width, 3)."""
    width, height = image.width(), image.height()
    pointer = image.constBits()
    stride = image.bytesPerLine()
    raw = np.frombuffer(memoryview(pointer), dtype=np.uint8, count=stride * height)
    raw = raw.reshape(height, stride)[:, : width * 3].reshape(height, width, 3)
    return raw.astype(np.float32) / 255.0


def _saturation(rgb: np.ndarray) -> np.ndarray:
    high = rgb.max(axis=2)
    low = rgb.min(axis=2)
    return np.where(high > 0, (high - low) / np.maximum(high, 1e-6), 0.0)


def _hue(rgb: np.ndarray) -> np.ndarray:
    """Hue in turns (0..1). Undefined for grey pixels; callers mask those out."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    high, low = rgb.max(axis=2), rgb.min(axis=2)
    span = np.maximum(high - low, 1e-6)
    hue = np.zeros_like(r)
    mask = high == r
    hue[mask] = ((g - b) / span)[mask] % 6.0
    mask = high == g
    hue[mask] = ((b - r) / span + 2.0)[mask]
    mask = high == b
    hue[mask] = ((r - g) / span + 4.0)[mask]
    return (hue / 6.0) % 1.0


def analyse(rgb: np.ndarray) -> FigureReading:
    """Turn an image array into observations and suggested answers."""
    reading = FigureReading()
    height, width, _ = rgb.shape
    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    ink = luminance < _INK_THRESHOLD
    coverage = float(ink.mean())

    if coverage < 0.001:
        reading.notes.append(
            "This image is almost blank, so nothing could be measured from it.")
        return reading

    ys, xs = np.nonzero(ink)
    cx, cy = xs.mean(), ys.mean()
    dx, dy = xs - cx, ys - cy
    radius = np.hypot(dx, dy)
    angle = np.arctan2(dy, dx)

    # --------------------------------------------------------- radial layout
    # Two signals, chosen by measuring the gallery rather than by intuition.
    # A first attempt used the angular spread of the outer ink, on the theory
    # that a fan puts tips all the way round; measured, it sat between 0.11 and
    # 0.36 for every layout alike and separated nothing.
    #
    # What does separate them is that **a fan has a hole in the middle**. Its
    # root sits at an inner radius and the ink is a ring, so the density near
    # the centroid is at or below the overall density. A rectangle is densest
    # exactly there. Aspect ratio corroborates it: a fan is square, a
    # rectangular phylogram is two to three times wider than tall.
    scale = max(radius.max(), 1e-6)
    inner_mask = radius < 0.25 * scale
    inner_area = np.pi * (0.25 * scale) ** 2
    total_area = np.pi * scale ** 2
    overall_density = ink.sum() / max(total_area, 1e-6)
    inner_density = inner_mask.sum() / max(inner_area, 1e-6)
    hollowness = float(inner_density / max(overall_density, 1e-9))
    aspect = width / max(height, 1)

    if 0.7 <= aspect <= 1.3 and hollowness < 2.5:
        reading.observations.append(Observation(
            key="shape", summary="The tree is drawn as a circular fan",
            evidence=(f"the figure is square (aspect {aspect:.2f}) and the "
                      f"middle is emptier than the rest ({hollowness:.1f}x the "
                      f"average ink density), which is the hole a fan leaves "
                      f"around its root"),
            confidence=0.85))
        reading.suggested["shape"] = "circular"
    elif aspect > 1.8 or hollowness > 4.5:
        reading.observations.append(Observation(
            key="shape", summary="The tree is drawn as a rectangle",
            evidence=(f"aspect {aspect:.2f} and the middle carries "
                      f"{hollowness:.1f}x the average ink density, where a fan "
                      f"would leave a hole"),
            confidence=0.8))
        reading.suggested["shape"] = "rectangular"
    else:
        reading.notes.append(
            f"The shape was ambiguous (aspect {aspect:.2f}, centre density "
            f"{hollowness:.1f}x average) -- an unrooted or radial layout looks "
            f"like this -- so the guide will ask you about it.")

    # ------------------------------------------------------ annotation colour
    saturation = _saturation(rgb)
    coloured = (saturation > _COLOUR_THRESHOLD) & ink
    colour_fraction = float(coloured.sum()) / float(max(ink.sum(), 1))

    if colour_fraction < 0.02:
        reading.observations.append(Observation(
            key="extra_data", summary="No annotation tracks; this is a bare tree",
            evidence=f"only {colour_fraction:.1%} of the ink is saturated colour",
            confidence=0.7))
        reading.suggested["extra_data"] = ["none"]
    else:
        hues = _hue(rgb)[coloured]
        counts = np.histogram(hues, bins=24, range=(0.0, 1.0))[0]
        distinct = int((counts > max(4, counts.sum() * 0.02)).sum())
        suggested: list[str] = []
        if distinct >= 3:
            suggested.append("category")
            reading.observations.append(Observation(
                key="extra_data",
                summary=f"Categorical colour, in roughly {distinct} distinct hues",
                evidence=(f"{colour_fraction:.0%} of the ink is saturated, "
                          f"spread across {distinct} separated hues"),
                confidence=0.7))
        else:
            suggested.append("matrix")
            reading.observations.append(Observation(
                key="extra_data",
                summary="A continuous colour scale, such as a heatmap or gradient",
                evidence=(f"{colour_fraction:.0%} of the ink is saturated but "
                          f"in only {distinct} hue band(s), which is what a "
                          f"colour ramp looks like"),
                confidence=0.6))
        reading.suggested["extra_data"] = suggested

    # -------------------------------------------------------------- scale cue
    if reading.suggested.get("shape") == "rectangular" and aspect < 0.75:
        reading.observations.append(Observation(
            key="tip_count",
            summary="Many tips: the figure is much taller than it is wide",
            evidence=f"aspect ratio {aspect:.2f}, typical of a long tip list",
            confidence=0.5))

    reading.notes.append(
        "These are measurements of the picture, not a reading of it. Change "
        "anything that does not match your data.")
    return reading


def inspect_figure(path: str) -> FigureReading:
    """Entry point registered for ``makeyourtree.figure_inspectors``."""
    image = load_image(path)
    reading = analyse(_to_array(image))
    reading.source = path
    return reading

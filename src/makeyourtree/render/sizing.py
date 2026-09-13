# SPDX-License-Identifier: MIT
"""Physical size and resolution: the arithmetic between scene units and paper.

**A scene unit is a PostScript point, 1/72 inch.**  That is the convention the
whole pipeline already used implicitly -- ``QPdfWriter`` is driven at 72 dpi and
the export dialog converts its DPI box with ``scale = dpi / 72`` -- but it was
never written down, so nothing could be checked against it.  It is written down
here, and :mod:`makeyourtree.render.svg` now emits ``pt`` so an SVG and a PDF of
the same figure are the same physical size.  Before that they differed by
96/72: an unqualified SVG length is a CSS pixel, and a CSS pixel is 1/96 inch.

The module is deliberately free of any rendering machinery.  It converts
numbers, so both the Qt-backed exporters and the Qt-free CLI can share one
answer to "how big is this, really", and a test can pin that answer without a
display server.

Resolution only applies to raster output.  A vector format has no pixels, so
``dpi`` is meaningless for SVG and PDF, and :func:`pixels_for` is the only place
it enters the arithmetic.
"""

from __future__ import annotations

import math
import re
from typing import Final

__all__ = [
    "POINTS_PER_INCH",
    "UNITS",
    "PAGE_SIZES",
    "LengthError",
    "parse_length",
    "format_length",
    "scale_for_dpi",
    "pixels_for",
    "page_size",
    "fit_scale",
]

POINTS_PER_INCH: Final[float] = 72.0

#: Multipliers onto points.  ``px`` is the CSS reference pixel, 1/96 inch --
#: not a device pixel, which has no fixed size and is what ``dpi`` is for.
UNITS: Final[dict[str, float]] = {
    "pt": 1.0,
    "px": POINTS_PER_INCH / 96.0,
    "in": POINTS_PER_INCH,
    "mm": POINTS_PER_INCH / 25.4,
    "cm": POINTS_PER_INCH / 2.54,
}

#: Named page sizes in points, portrait.  Journals ask for a column or a page
#: width far more often than for a pixel count, so the common ones are here
#: rather than left to the reader's arithmetic.
PAGE_SIZES: Final[dict[str, tuple[float, float]]] = {
    "a5": (420.0, 595.0),
    "a4": (595.0, 842.0),
    "a3": (842.0, 1191.0),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
    "tabloid": (792.0, 1224.0),
    # Single- and double-column widths used by most journals, as heights of 0
    # meaning "whatever the figure needs".
    "column": (255.0, 0.0),
    "wide-column": (539.0, 0.0),
}

_LENGTH_RE = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z]*)\s*$")


class LengthError(ValueError):
    """A length string could not be understood."""


def parse_length(text: str | float | int) -> float:
    """Return *text* in points.

    A bare number is already points, so ``"400"`` and ``"400pt"`` agree.  This
    keeps every existing ``--width 900`` invocation meaning exactly what it
    meant before units were accepted at all.

    >>> parse_length("180mm")
    510.23...
    >>> parse_length(72)
    72.0
    """
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        value = float(text)
        if not math.isfinite(value):
            raise LengthError(f"length must be finite, got {text!r}")
        return value

    match = _LENGTH_RE.match(str(text))
    if match is None:
        raise LengthError(
            f"cannot read {text!r} as a length; write a number optionally "
            f"followed by one of {', '.join(sorted(UNITS))}")
    number, unit = match.group(1), match.group(2).lower()
    try:
        value = float(number)
    except ValueError as exc:  # pragma: no cover - the regex already limits this
        raise LengthError(f"cannot read {text!r} as a length") from exc
    if not math.isfinite(value):
        raise LengthError(f"length must be finite, got {text!r}")
    if not unit:
        return value
    if unit not in UNITS:
        raise LengthError(
            f"unknown unit {unit!r} in {text!r}; use one of "
            f"{', '.join(sorted(UNITS))}")
    return value * UNITS[unit]


def format_length(points: float, unit: str = "mm", *, decimals: int = 1) -> str:
    """Render *points* in *unit*, for a message a human will read."""
    if unit not in UNITS:
        raise LengthError(f"unknown unit {unit!r}")
    return f"{points / UNITS[unit]:.{decimals}f}{unit}"


def scale_for_dpi(dpi: float) -> float:
    """Rasterisation factor that puts *dpi* device pixels in every inch.

    One scene unit is 1/72 inch, so 72 dpi is 1:1 and 300 dpi is 300/72.
    """
    if not math.isfinite(dpi) or dpi <= 0:
        raise ValueError(f"dpi must be a positive number, got {dpi!r}")
    return float(dpi) / POINTS_PER_INCH


def pixels_for(points: float, dpi: float) -> int:
    """Pixel count for *points* at *dpi*, at least one.

    Rounds half up rather than taking the ceiling, so that a size derived from a
    pixel count and converted back does not gain a pixel to floating-point
    noise.  This matches ``png_size`` in the studio exporter, and the two must
    agree or the dialog's predicted size stops being the produced size.
    """
    value = float(points) * scale_for_dpi(dpi)
    return max(1, int(math.floor(value + 0.5)))


def page_size(name: str) -> tuple[float, float]:
    """A named page size in points, portrait.

    A height of ``0.0`` means the caller should leave the height to the figure,
    which is what the column widths want: a journal specifies how wide a figure
    may be and lets it be as tall as it needs.
    """
    key = str(name).strip().lower()
    if key not in PAGE_SIZES:
        raise LengthError(
            f"unknown page size {name!r}; use one of "
            f"{', '.join(sorted(PAGE_SIZES))}")
    return PAGE_SIZES[key]


def fit_scale(scene_width: float, scene_height: float,
              max_width: float | None = None,
              max_height: float | None = None) -> float:
    """Largest factor that fits the scene inside the given bounds.

    Returns 1.0 when neither bound is given.  Never enlarges beyond the bounds
    and never returns a non-positive factor, so a degenerate scene cannot
    produce a zero-pixel image.
    """
    factors = []
    if max_width is not None and scene_width > 0:
        factors.append(float(max_width) / float(scene_width))
    if max_height is not None and scene_height > 0:
        factors.append(float(max_height) / float(scene_height))
    if not factors:
        return 1.0
    return max(min(factors), 1e-6)

# SPDX-License-Identifier: MIT
"""Scale bar and axis ticks for length-scaled trees.

A scale bar answers one question -- "how long is a branch?" -- and it may only
be shown when the along coordinate actually came from branch length.  In a
cladogram the along axis encodes topology, so a bar there would be a lie;
:func:`scale_bar` returns ``None`` rather than drawing one.

Both the bar and the axis pick their round numbers with Heckbert's
loose/tight labelling (Paul S. Heckbert, "Nice Numbers for Graph Labels", in
*Graphics Gems*, Academic Press, 1990, pp. 61-63): snap a magnitude to the
1 / 2 / 5 / 10 mantissa ladder, choosing the nearest rung when a *loose*
approximation is wanted and the next rung up when the value must not be
exceeded.  They share :func:`nice_num` on purpose -- a bar reading "0.2" beside
an axis tick ladder stepping by 0.25 is the kind of disagreement readers
notice immediately.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..style.theme import Theme
from .along import along_is_length
from .params import LayoutMode, LayoutParams

if TYPE_CHECKING:  # pragma: no cover
    from .frame import LayoutFrame

__all__ = ["nice_num", "ScaleBar", "scale_bar", "axis_ticks"]

TARGET_FRACTION = 0.15
"""Fraction of the tree body a bar aims to span before rounding."""

MIN_BAR = 28.0
"""Scene units below which a bar is too short to read a length off."""


def nice_num(x: float, round_: bool = True) -> float:
    """Snap *x* to the 1 / 2 / 5 / 10 mantissa ladder.

    With ``round_`` the nearest rung is chosen (Heckbert's *loose* labelling,
    used for a target size that may be over- or undershot); without it the
    smallest rung that is at least *x* is chosen (*tight* labelling, used when
    the result must not fall below a minimum).  Non-positive input has no
    magnitude to snap, so it returns ``0.0`` rather than reaching ``log10(0)``.
    """
    if x <= 0.0 or not math.isfinite(x):
        return 0.0
    exp = math.floor(math.log10(x))
    frac = x / 10.0 ** exp
    if round_:
        nf = 1.0 if frac < 1.5 else 2.0 if frac < 3.0 else 5.0 if frac < 7.0 else 10.0
    else:
        nf = 1.0 if frac <= 1.0 else 2.0 if frac <= 2.0 else 5.0 if frac <= 5.0 else 10.0
    if nf == 10.0:
        # Return the next decade's 1 exactly, so callers can rely on the
        # mantissa of the result being one of 1, 2 or 5 without float fuzz.
        return 10.0 ** (exp + 1)
    return nf * 10.0 ** exp


@dataclass(frozen=True, slots=True)
class ScaleBar:
    """One drawn bar: how much tree it spans and where to put it."""

    units: float
    """Length in tree units -- substitutions per site, years, whatever the
    branch lengths mean."""
    pixels: float
    """Length in scene units.  Always ``units * frame.scale``."""
    label: str
    x: float
    y: float
    """Suggested anchor: the left end of the bar, below the tree body.  A
    suggestion only -- the compositor may move it to fit the page."""

    @property
    def position(self) -> tuple[float, float]:
        return (self.x, self.y)


def scale_bar(frame: "LayoutFrame", params: LayoutParams,
              theme: Theme) -> ScaleBar | None:
    """A round-numbered bar for *frame*, or ``None`` when one would mislead.

    ``None`` is returned whenever a bar would have no meaning: a cladogram,
    whose along coordinate is topological; a degenerate scale (a star tree, or
    a topology-only file drawn as a phylogram), where no number of scene units
    corresponds to any branch length; and a ``RADIAL`` fan, which lays its
    along axis out topologically however it was asked to.  All three are one
    question -- did this pass actually realise a length axis? -- and
    :func:`makeyourtree.layout.along.along_is_length` answers it from what the
    layout published rather than from what the user requested.  A theme that
    has turned the bar off also returns ``None``, so callers need only ask once.
    """
    if not theme.scalebar_show or not along_is_length(frame, params):
        return None
    scale = frame.scale

    extent = _along_extent(frame)
    span = _tree_span(frame, scale, extent)
    units = nice_num(TARGET_FRACTION * extent / scale, round_=True)
    if units * scale < MIN_BAR:
        units = nice_num(MIN_BAR / scale, round_=False)
    if span > 0.0 and units > span * 0.5:
        # One outlier tip can make the fitted scale so small that the "nice"
        # unit is longer than the tree; a bar you cannot lay against the
        # drawing is worse than a slightly odd number.
        units = nice_num(span * 0.5, round_=False)
    if units <= 0.0:
        return None

    x0, _, _, y1 = frame.body_bounds
    gap = max(theme.scalebar_size * 2.0, params.row_spacing)
    return ScaleBar(units=units, pixels=units * scale,
                    label=_label(units, params), x=x0, y=y1 + gap)


def axis_ticks(frame: "LayoutFrame", params: LayoutParams, *,
               count: int = 6) -> list[tuple[float, float, str]]:
    """``(value, position, label)`` for a full along-axis, root to deepest tip.

    Ticks land on multiples of a step drawn from the same mantissa ladder as
    :func:`scale_bar`, so the two never disagree about what a round number is.
    Positions are accumulated as ``first + k * step`` rather than by repeated
    addition: at small steps the drift of a running sum shows up as duplicate
    labels like ``0.3`` and ``0.30000000000000004``.

    ``[]`` wherever :func:`scale_bar` returns ``None``, and additionally in
    ``UNROOTED``: an unrooted drawing has a meaningful *scale* but no origin to
    measure an axis from, so a ladder of rules across it would be labelling
    distances from an arbitrary corner of the bounding box.  Positions are
    scene ``x`` for a linear frame and a radius for a polar one, measured from
    ``metadata["base_radius"]`` so the central hole is not counted as tree.
    """
    if not along_is_length(frame, params) or frame.mode is LayoutMode.UNROOTED:
        return []
    scale = frame.scale
    hi = _tree_span(frame, scale, _along_extent(frame))
    if hi <= 0.0:
        return []
    target = max(2, count)

    step = nice_num(nice_num(hi, round_=False) / (target - 1), round_=True)
    if step <= 0.0:
        return []
    decimals = max(0, -int(math.floor(math.log10(step))))
    origin = _along_origin(frame)
    out: list[tuple[float, float, str]] = []
    for k in range(int(hi / step) + 2):
        value = k * step
        if value > hi + 1e-9:
            break
        out.append((value, origin + value * scale, f"{value:.{decimals}f}"))
    return out


# --------------------------------------------------------------- internals


def _along_extent(frame: "LayoutFrame") -> float:
    """Scene-space length of the tree body along its along-axis."""
    if frame.mode.is_polar:
        return frame.max_radius
    x0, _, x1, _ = frame.body_bounds
    return x1 - x0


def _along_origin(frame: "LayoutFrame") -> float:
    """Scene coordinate of zero branch length on the along-axis."""
    if frame.mode.is_polar:
        return float(frame.metadata.get("base_radius", 0.0))
    return frame.body_bounds[0]


def _tree_span(frame: "LayoutFrame", scale: float, extent: float) -> float:
    """Root-to-deepest-tip length in tree units."""
    recorded = frame.metadata.get("depth_max")
    if recorded:
        return float(recorded)
    return extent / scale if scale > 0 else 0.0


def _label(units: float, params: LayoutParams) -> str:
    text = _format_units(units)
    name = params.extra.get("scale_unit")
    return f"{text} {name}" if name else text


def _format_units(u: float) -> str:
    """Shortest exact-looking rendering of a ladder value.

    Ladder values are 1, 2 or 5 times a power of ten, so one digit past the
    leading one is always enough; the trailing-zero strip then removes what
    that digit did not need.  The strip applies only when there is a decimal
    point: on an integer rendering it would eat significant zeros and label a
    bar of 100 as "1".
    """
    if u == 0.0:
        return "0"
    a = abs(u)
    if a >= 1e5 or a < 1e-4:
        return f"{u:.0e}".replace("e+0", "e").replace("e-0", "e-").replace("e+", "e")
    decimals = max(0, -int(math.floor(math.log10(a))) + 1)
    text = f"{u:.{min(decimals, 8)}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"

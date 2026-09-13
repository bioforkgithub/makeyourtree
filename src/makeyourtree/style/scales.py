# SPDX-License-Identifier: MIT
"""Value-to-colour mappings.

A *scale* is the only thing that stands between a column of annotation values
and a coloured mark, and it owns two responsibilities that are easy to get
wrong separately: it must answer ``color_of(value)`` for every cell, and it
must be able to describe itself as a legend that matches those cells exactly.
Keeping both in one object is what stops a legend gradient drawn from two
endpoints disagreeing with cells drawn from a nine-stop ramp.

Three concrete scales cover the annotation tracks:

:class:`ContinuousScale`
    Numeric domain sampled from a ramp, with linear, log or symlog spacing.
:class:`CategoricalScale`
    Discrete labels with a pinned label-to-colour mapping.
:class:`BinnedScale`
    Numeric domain cut into classes -- quantile classes via
    :func:`quantile_breaks`, or user-supplied breaks.

Missing data is a first-class answer: ``color_of`` returns ``None`` for it and
the caller draws a gap.  Returning a colour for missing data (black, or the
bottom of the ramp) is the classic way to make an empty cell look like the most
extreme measurement in the dataset.

Conventions follow standard practice for thematic maps -- see Slocum et al.,
*Thematic Cartography and Geovisualization*, on classed vs unclassed choropleth
mapping and on why a diverging scheme needs a domain symmetric about its
midpoint.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..core.diagnostics import DiagnosticSink
from .color import Color, parse_color
from .palettes import Palette, assign_categories, get_palette

__all__ = ["Scale", "LegendItem", "ContinuousScale", "CategoricalScale",
           "BinnedScale", "quantile_breaks", "make_scale", "MISSING"]

MISSING: frozenset[str] = frozenset({"", "-", "na", "n/a", "nan", "none", "null"})
"""Cell texts that mean "no value here".  ``-`` is the spelling used by the
``.mytrack`` grammar; the rest turn up constantly in exported spreadsheets."""

_FMT = "{:.4g}"


@dataclass(frozen=True, slots=True)
class LegendItem:
    """One legend row.

    Field-for-field identical to :class:`makeyourtree.tracks.base.LegendItem` and
    deliberately not imported from there: ``style`` sits below ``tracks`` in the
    dependency order (tracks imports style, not the other way round), and a
    scale must remain usable without the track machinery.  A track can hand
    these straight to :class:`~makeyourtree.tracks.base.Legend`.
    """

    label: str
    color: Color | None = None
    shape: str = "square"
    gradient: tuple[Color, ...] | None = None
    value_range: tuple[float, float] | None = None


@runtime_checkable
class Scale(Protocol):
    """What every colour scale must offer."""

    kind: str
    """``categorical``, ``sequential``, ``diverging`` or ``binned``."""

    def color_of(self, value: Any) -> Color | None:
        """Colour for one cell, or ``None`` when there is no value to show."""

    def legend_items(self) -> list[LegendItem]:
        """Legend rows describing this scale, in display order."""


# ------------------------------------------------------------------ helpers


def to_float(value: Any) -> float | None:
    """Coerce a cell to a finite float, or ``None``.

    Annotation values arrive as strings far more often than as numbers, and a
    lenient reader must not raise on the one row that says ``n/a``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    s = str(value).strip()
    if not s or s.lower() in MISSING:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and not math.isfinite(value):
        return True
    return str(value).strip().lower() in MISSING


def _fmt(v: float) -> str:
    return _FMT.format(v)


# ---------------------------------------------------------------- continuous


class ContinuousScale:
    """Numeric domain mapped onto a ramp.

    *transform* re-spaces the domain before sampling:

    ``linear``
        Equal value differences get equal colour differences.
    ``log``
        Base-10; for data spanning orders of magnitude (abundances, counts).
        Requires a strictly positive domain.
    ``symlog``
        Log outside ``[-linthresh, +linthresh]`` and linear inside it, so a
        signed quantity that passes through zero can still use log spacing
        (Webber 2013, *Measurement Science and Technology*, on the bi-symmetric
        log transform).

    A log scale asked for a domain that includes zero cannot be honoured, and
    refusing to draw anything would be a poor trade for one bad option.  It
    degrades to linear instead and raises :attr:`degraded`, which the caller
    reports through :meth:`report`.

    Passing *mid* makes the domain symmetric about that midpoint, which is the
    only correct domain for a diverging ramp: otherwise the neutral colour sits
    off-centre and every reading of "which side is bigger" is wrong.
    """

    __slots__ = ("vmin", "vmax", "palette", "clamp", "transform", "linthresh",
                 "nan_color", "mid", "title", "degraded", "degraded_reason",
                 "_flo", "_fhi")

    def __init__(self, vmin: float, vmax: float,
                 palette: str | Palette = "viridis", *,
                 clamp: bool = True, transform: str = "linear",
                 mid: float | None = None, linthresh: float = 1.0,
                 nan_color: str | Color | None = None,
                 title: str = "") -> None:
        vmin, vmax = float(vmin), float(vmax)
        if vmax < vmin:
            vmin, vmax = vmax, vmin
        if mid is not None:
            m = max(abs(vmin - mid), abs(vmax - mid))
            vmin, vmax = mid - m, mid + m
        self.vmin = vmin
        self.vmax = vmax
        self.mid = mid
        self.palette = get_palette(palette)
        self.clamp = clamp
        self.linthresh = abs(float(linthresh)) or 1.0
        self.nan_color = parse_color(nan_color) if isinstance(nan_color, str) else nan_color
        self.title = title
        self.degraded = False
        self.degraded_reason: str | None = None

        t = str(transform).lower()
        if t not in ("linear", "log", "symlog"):
            self._degrade(f"unknown transform {transform!r}; using linear")
            t = "linear"
        elif t == "log" and (vmin <= 0.0 or vmax <= 0.0):
            self._degrade(f"log transform needs a positive domain, got "
                          f"[{_fmt(vmin)}, {_fmt(vmax)}]; using linear")
            t = "linear"
        self.transform = t
        self._flo = self._forward(vmin)
        self._fhi = self._forward(vmax)

    # -------------------------------------------------------------- domain

    def _degrade(self, reason: str) -> None:
        self.degraded = True
        self.degraded_reason = reason

    def _forward(self, v: float) -> float:
        if self.transform == "log":
            return math.log10(v)
        if self.transform == "symlog":
            a = abs(v)
            if a <= self.linthresh:
                return v
            return math.copysign(self.linthresh * (1.0 + math.log10(a / self.linthresh)), v)
        return v

    def _inverse(self, f: float) -> float:
        if self.transform == "log":
            return 10.0 ** f
        if self.transform == "symlog":
            a = abs(f)
            if a <= self.linthresh:
                return f
            return math.copysign(self.linthresh * 10.0 ** (a / self.linthresh - 1.0), f)
        return f

    def normalise(self, value: Any) -> float | None:
        """Position of *value* in the domain as 0..1, or ``None``.

        ``None`` means "do not colour this cell": the value is missing, is not a
        number, is non-positive under a log transform, or lies outside the
        domain while *clamp* is off.
        """
        v = to_float(value)
        if v is None:
            return None
        if self.transform == "log" and v <= 0.0:
            return None
        lo, hi = self._flo, self._fhi
        if hi == lo:
            return 0.5
        t = (self._forward(v) - lo) / (hi - lo)
        if self.clamp:
            return max(0.0, min(1.0, t))
        if t < 0.0 or t > 1.0:
            return None
        return t

    # ------------------------------------------------------------- protocol

    @property
    def kind(self) -> str:
        return "diverging" if self.mid is not None else "sequential"

    def color_of(self, value: Any) -> Color | None:
        t = self.normalise(value)
        if t is None:
            return self.nan_color
        return self.palette.sample(t)

    def ticks(self, n: int = 5) -> list[float]:
        """*n* tick values evenly spaced in *transformed* space, so a log scale
        gets decade-ish ticks rather than ticks bunched at the bottom."""
        if n < 2:
            return [self.vmin]
        return [self._inverse(self._flo + (self._fhi - self._flo) * i / (n - 1))
                for i in range(n)]

    def legend_items(self) -> list[LegendItem]:
        """One gradient row sampled at nine stops, plus a detached swatch for
        missing data when the caller asked for one.  Nine stops because a
        two-stop gradient does not reproduce a ramp that turns in the middle."""
        items = [LegendItem(label=f"{_fmt(self.vmin)} – {_fmt(self.vmax)}",
                            shape="gradient",
                            gradient=self.palette.resample(9),
                            value_range=(self.vmin, self.vmax))]
        if self.nan_color is not None:
            items.append(LegendItem(label="no data", color=self.nan_color))
        return items

    def report(self, sink: DiagnosticSink | None) -> None:
        """Push any construction-time degradation into *sink*."""
        if self.degraded and sink is not None and self.degraded_reason:
            sink.warn("scale.transform", self.degraded_reason)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (f"<ContinuousScale {_fmt(self.vmin)}..{_fmt(self.vmax)} "
                f"{self.transform} {self.palette.name}>")


# --------------------------------------------------------------- categorical


class CategoricalScale:
    """Discrete labels with a fixed label-to-colour mapping.

    The mapping is the state worth keeping: it is what a project file stores so
    that re-rooting, filtering or reloading the tree cannot reshuffle the
    colours.  Build it once with
    :func:`~makeyourtree.style.palettes.assign_categories` and hold on to it.
    """

    __slots__ = ("mapping", "palette", "other_color", "title", "kind")

    def __init__(self, mapping: Mapping[str, Any] | Iterable[Any],
                 palette: str | Palette = "okabe-ito", *,
                 other_color: str | Color | None = None,
                 title: str = "") -> None:
        self.palette = get_palette(palette)
        if isinstance(mapping, Mapping):
            self.mapping: dict[str, Color] = {
                str(k): v if isinstance(v, Color) else parse_color(v)
                for k, v in mapping.items()}
        else:
            self.mapping = assign_categories(mapping, self.palette)
        self.other_color = (parse_color(other_color)
                            if isinstance(other_color, str) else other_color)
        self.title = title
        self.kind = "categorical"

    @property
    def categories(self) -> list[str]:
        return list(self.mapping)

    def color_of(self, value: Any) -> Color | None:
        """Unknown labels fall to *other_color*, and to ``None`` when no such
        colour was configured -- an unlisted category is closer to "no data"
        than to any colour the palette happens to have left over."""
        if is_missing(value):
            return None
        return self.mapping.get(str(value).strip(), self.other_color)

    def legend_items(self) -> list[LegendItem]:
        items = [LegendItem(label=k, color=c) for k, c in self.mapping.items()]
        if self.other_color is not None:
            items.append(LegendItem(label="other", color=self.other_color))
        return items

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<CategoricalScale n={len(self.mapping)} {self.palette.name}>"


# -------------------------------------------------------------------- binned


def quantile_breaks(values: Iterable[Any], n: int) -> tuple[float, ...]:
    """Break points cutting *values* into *n* classes of equal count.

    Quantile classing, as opposed to equal-interval classing, keeps every class
    populated, which is what a skewed distribution (most annotation data) needs
    if the map is not to come out one flat colour.  Quantiles use the standard
    linear-interpolation definition (Hyndman & Fan 1996, type 7).

    Ties collapse: repeated break points are dropped, so asking for five
    classes of data with three distinct values gives three edges, not five.
    """
    xs = sorted(v for v in (to_float(x) for x in values) if v is not None)
    if not xs:
        return ()
    n = max(1, int(n))
    edges: list[float] = []
    for i in range(n + 1):
        p = i / n
        pos = p * (len(xs) - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, len(xs) - 1)
        edges.append(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))
    out = [edges[0]]
    for e in edges[1:]:
        if e > out[-1]:
            out.append(e)
    if len(out) == 1:
        out.append(out[0])
    return tuple(out)


class BinnedScale:
    """Numeric domain cut into classes at *breaks*.

    *breaks* are the class **edges**: ``len(breaks) - 1`` classes, edge *i*
    opening class *i*.  Classes are half-open ``[lo, hi)`` except the last,
    which is closed so that the maximum of the data lands inside the scale
    rather than one pixel outside it.
    """

    __slots__ = ("breaks", "palette", "clamp", "colors", "title", "kind")

    def __init__(self, breaks: Sequence[float], palette: str | Palette = "viridis",
                 *, clamp: bool = True, title: str = "") -> None:
        edges = sorted(float(b) for b in breaks)
        if len(edges) < 2:
            raise ValueError("BinnedScale needs at least two break points")
        self.breaks = tuple(edges)
        self.palette = get_palette(palette)
        self.clamp = clamp
        self.title = title
        self.kind = "binned"
        n = len(self.breaks) - 1
        # Sample class centres, not class edges: sampling edges wastes half the
        # ramp on colours no class ever uses.
        if self.palette.kind == "categorical":
            self.colors = tuple(self.palette.cycle(i) for i in range(n))
        else:
            self.colors = tuple(self.palette.sample((i + 0.5) / n) for i in range(n))

    @property
    def n_bins(self) -> int:
        return len(self.breaks) - 1

    def bin_of(self, value: Any) -> int | None:
        v = to_float(value)
        if v is None:
            return None
        if v < self.breaks[0]:
            return 0 if self.clamp else None
        if v >= self.breaks[-1]:
            # Closed top edge: the maximum belongs to the last class.
            return self.n_bins - 1 if (self.clamp or v == self.breaks[-1]) else None
        return min(bisect.bisect_right(self.breaks, v) - 1, self.n_bins - 1)

    def color_of(self, value: Any) -> Color | None:
        i = self.bin_of(value)
        return None if i is None else self.colors[i]

    def legend_items(self) -> list[LegendItem]:
        return [LegendItem(label=f"{_fmt(self.breaks[i])} – {_fmt(self.breaks[i + 1])}",
                           color=self.colors[i],
                           value_range=(self.breaks[i], self.breaks[i + 1]))
                for i in range(self.n_bins)]

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<BinnedScale bins={self.n_bins} {self.palette.name}>"


# ------------------------------------------------------------------ factory

DEFAULT_PALETTES: dict[str, str] = {
    "categorical": "okabe-ito",
    "sequential": "viridis",
    "diverging": "blue-red",
    "binned": "viridis",
}

_DISTINCT_LIMIT = 6
"""At or below this many distinct whole numbers, a numeric column is read as
class codes rather than as a measurement.  Six is where a categorical legend
stops being easier to read than a ramp."""


def infer_kind(values: Iterable[Any], *, mid: float = 0.0,
               distinct_limit: int = _DISTINCT_LIMIT) -> str:
    """Guess which scale a column wants.

    Non-numeric, or few enough whole numbers to be class codes, means
    categorical.  A numeric range that straddles *mid* has a meaningful centre
    (log ratios, z-scores, differences from a reference) and wants a diverging
    ramp so the sign is visible at a glance.  Everything else is sequential.
    """
    present = [v for v in values if not is_missing(v)]
    if not present:
        return "categorical"
    nums = [to_float(v) for v in present]
    if any(v is None for v in nums):
        return "categorical"
    xs = [v for v in nums if v is not None]
    distinct = sorted(set(xs))
    if len(distinct) <= distinct_limit and all(float(x).is_integer() for x in distinct):
        return "categorical"
    if distinct[0] < mid < distinct[-1]:
        return "diverging"
    return "sequential"


def make_scale(values: Iterable[Any], *, kind: str = "auto",
               palette: str | Palette | None = None, **kw: Any) -> Scale:
    """Build the scale a column of *values* wants.

    ``kind="auto"`` delegates to :func:`infer_kind`; naming a kind forces it.
    Surplus keyword arguments go to the chosen scale's constructor, so
    ``make_scale(v, transform="log")`` works without the caller knowing which
    class it will get.
    """
    vals = list(values)
    mid = float(kw.pop("mid", 0.0) or 0.0)
    distinct_limit = int(kw.pop("distinct_limit", _DISTINCT_LIMIT))
    if kind == "auto":
        kind = infer_kind(vals, mid=mid, distinct_limit=distinct_limit)
    if kind not in DEFAULT_PALETTES:
        raise ValueError(f"unknown scale kind {kind!r}; "
                         f"known: auto, {', '.join(sorted(DEFAULT_PALETTES))}")
    pal = get_palette(palette if palette is not None else DEFAULT_PALETTES[kind])

    if kind == "categorical":
        fixed = kw.pop("fixed", None)
        mapping = assign_categories(vals, pal, fixed)
        return CategoricalScale(mapping, pal, **kw)

    xs = [v for v in (to_float(x) for x in vals) if v is not None]
    if kind == "binned":
        bins = int(kw.pop("bins", 5))
        breaks = kw.pop("breaks", None) or quantile_breaks(xs, bins)
        if len(breaks) < 2:
            breaks = (0.0, 1.0)
        return BinnedScale(breaks, pal, **kw)

    # An empty or single-valued numeric column still needs a usable domain;
    # a zero-width one would make every cell the same arbitrary colour.
    lo, hi = (min(xs), max(xs)) if xs else (0.0, 1.0)
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    if kind == "diverging":
        kw.setdefault("mid", mid)
    return ContinuousScale(lo, hi, pal, **kw)

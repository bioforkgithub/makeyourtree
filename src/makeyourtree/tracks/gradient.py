# SPDX-License-Identifier: MIT
"""Gradient strip: one continuous value per tip, and the shared colour ramp.

:class:`ColorRamp` interpolates in **OKLab** (Ottosson, 2020, *A perceptual
colour space for image processing*).  A straight sRGB interpolation between two
saturated hues dips in lightness and desaturates through the middle of the
range, which a reader sees as a spurious band of "low" cells halfway up the
scale; OKLab keeps lightness monotone, so the ramp reads in the order the data
is in.

The ramp also **quantises**: it precomputes a fixed number of steps and returns
one of those.  Two reasons.  Colour equality then merges runs of similar cells
in :class:`~makeyourtree.tracks.shapes.QuadBatch`, and in polar layouts -- where a
cell cannot be an axis-aligned rectangle and the batch must group by colour --
it bounds the mark count by the step count instead of by the cell count.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from ..scene.compose import compositor_owns_titles
from ..scene.marks import Anchor, Baseline, MarkSink, TextMark, TextStyle
from ..style.color import Color, parse_color
from .base import Legend, LegendItem, Track, TrackContext, register
from .shapes import QuadBatch

__all__ = ["GradientTrack", "ColorRamp", "ramp_from_options",
           "DEFAULT_SEQUENTIAL", "DEFAULT_MISSING", "to_float"]

DEFAULT_SEQUENTIAL: tuple[str, str, str] = ("#FBF7EC", "#3D9AB8", "#16265E")
"""Our own light-to-dark sequential ramp: warm near-white, mid teal, deep
indigo.  Monotone in OKLab lightness, so it survives greyscale printing."""

DEFAULT_MISSING = "#6E6E76"
"""Neutral grey for "no value".  Chosen to sit far from every colour the
sequential ramp produces, so a missing cell is never mistaken for a low one."""


def to_float(value: Any) -> float | None:
    """Finite float, or None for anything that is not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ------------------------------------------------------------------- OKLab


def _srgb_to_oklab(c: Color) -> tuple[float, float, float]:
    def lin(v: int) -> float:
        x = v / 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = lin(c.r), lin(c.g), lin(c.b)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = _cbrt(l), _cbrt(m), _cbrt(s)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _oklab_to_srgb(lab: tuple[float, float, float], alpha: int) -> Color:
    L, a, b = lab
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    def enc(v: float) -> int:
        v = 12.92 * v if v <= 0.0031308 else 1.055 * (max(v, 0.0) ** (1 / 2.4)) - 0.055
        return max(0, min(255, int(round(v * 255.0))))

    return Color(enc(r), enc(g), enc(bl), alpha)


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


class ColorRamp:
    """Value -> colour over a numeric domain, interpolated in OKLab."""

    __slots__ = ("stops", "domain", "steps", "_table")

    def __init__(self, stops: Sequence[Any] = DEFAULT_SEQUENTIAL,
                 domain: tuple[float, float] = (0.0, 1.0), *,
                 steps: int = 256) -> None:
        cols = [parse_color(s) for s in stops] or [parse_color(DEFAULT_SEQUENTIAL[0])]
        if len(cols) == 1:
            cols = [cols[0], cols[0]]
        self.stops: tuple[Color, ...] = tuple(cols)
        self.domain = (float(domain[0]), float(domain[1]))
        self.steps = max(2, int(steps))
        self._table: tuple[Color, ...] = self._build()

    def _build(self) -> tuple[Color, ...]:
        labs = [_srgb_to_oklab(c) for c in self.stops]
        alphas = [c.a for c in self.stops]
        n_seg = len(labs) - 1
        out: list[Color] = []
        for i in range(self.steps):
            t = i / (self.steps - 1)
            pos = t * n_seg
            k = min(int(pos), n_seg - 1)
            f = pos - k
            a0, a1 = labs[k], labs[k + 1]
            lab = (a0[0] + (a1[0] - a0[0]) * f,
                   a0[1] + (a1[1] - a0[1]) * f,
                   a0[2] + (a1[2] - a0[2]) * f)
            alpha = int(round(alphas[k] + (alphas[k + 1] - alphas[k]) * f))
            out.append(_oklab_to_srgb(lab, alpha))
        return tuple(out)

    # ---------------------------------------------------------------- use

    def normalise(self, value: Any) -> float | None:
        """Value mapped into ``[0, 1]``, or None when it is not a number.

        A degenerate domain maps everything to the middle of the ramp: with one
        distinct value there is no "high" and "low" to distinguish, and picking
        an end would imply one.
        """
        f = to_float(value)
        if f is None:
            return None
        lo, hi = self.domain
        if hi - lo <= 0:
            return 0.5
        return min(1.0, max(0.0, (f - lo) / (hi - lo)))

    def at(self, t: float) -> Color:
        """Colour at normalised position *t*, quantised to the step table."""
        i = int(round(min(1.0, max(0.0, t)) * (self.steps - 1)))
        return self._table[i]

    def color(self, value: Any) -> Color | None:
        t = self.normalise(value)
        return None if t is None else self.at(t)

    def __call__(self, value: Any) -> Color | None:
        return self.color(value)

    def sample(self, n: int = 16) -> tuple[Color, ...]:
        """*n* colours evenly spaced across the ramp, for a legend bar."""
        n = max(2, n)
        return tuple(self.at(i / (n - 1)) for i in range(n))


def ramp_from_options(opts: dict[str, Any], domain: tuple[float, float]) -> ColorRamp:
    """Build a ramp from the colour options shared by gradient and heatmap."""
    stops = opts.get("stops")
    if not stops:
        if opts.get("use_mid", True) and opts.get("color_mid"):
            stops = [opts.get("color_min") or DEFAULT_SEQUENTIAL[0],
                     opts["color_mid"],
                     opts.get("color_max") or DEFAULT_SEQUENTIAL[2]]
        else:
            stops = [opts.get("color_min") or DEFAULT_SEQUENTIAL[0],
                     opts.get("color_max") or DEFAULT_SEQUENTIAL[2]]
    return ColorRamp(stops, domain, steps=int(opts.get("ramp_steps", 256)))


@register
class GradientTrack(Track):
    """A band per tip, coloured by one continuous value."""

    type_id = "gradient"
    display_name = "Gradient"
    needs_numeric = True

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        o = super().default_options()
        o.update({
            "thickness": 22.0,
            "margin": 0.0,
            "color_min": DEFAULT_SEQUENTIAL[0],
            "color_mid": DEFAULT_SEQUENTIAL[1],
            "color_max": DEFAULT_SEQUENTIAL[2],
            "use_mid": True,
            "stops": None,
            "ramp_steps": 256,
            "min_value": None,
            "max_value": None,
            "missing": "skip",
            "missing_color": DEFAULT_MISSING,
            "missing_label": "no value",
            "merge_runs": True,
            "title_size": None,
            "legend_samples": 24,
        })
        return o

    # -------------------------------------------------------------- scale

    def domain(self) -> tuple[float, float]:
        """Value range: the user's override where given, else the data's."""
        lo = self.opt("min_value")
        hi = self.opt("max_value")
        found = self.data.value_range(0) or (0.0, 1.0)
        return (float(lo) if lo is not None else found[0],
                float(hi) if hi is not None else found[1])

    def ramp(self) -> ColorRamp:
        return ramp_from_options(self.options, self.domain())

    def _missing_color(self) -> Color | None:
        if self.opt("missing") != "fill":
            return None
        spec = self.opt("missing_color")
        try:
            return parse_color(spec) if spec else None
        except ValueError:
            return None

    # ------------------------------------------------------------ protocol

    def measure(self, ctx: TrackContext) -> float:
        return float(self.opt("margin", 0.0)) + float(self.opt("thickness", 22.0))

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        ramp = self.ramp()
        miss = self._missing_color()
        off0 = ctx.offset + float(self.opt("margin", 0.0))
        off1 = off0 + float(self.opt("thickness", 22.0))
        border = self.opt("border_color")
        batch = QuadBatch(
            ctx.projector, opacity=float(self.opt("opacity", 1.0)),
            stroke=parse_color(border) if border else None,
            stroke_width=float(self.opt("border_width", 0.0)))

        merge = bool(self.opt("merge_runs", True))
        run_color: Color | None = None
        run_lo = run_hi = 0.0
        for nid in ctx.tip_ids():
            present = nid in self.data.rows
            c = ramp.color(self.data.get(nid, 0)) if present else None
            if c is None and present:
                c = miss
            lo, hi = ctx.rows_of(nid)
            if c is not None and merge and c == run_color and lo <= run_hi + 1e-9:
                run_hi = hi
                continue
            if run_color is not None:
                batch.add(run_lo, run_hi, off0, off1, run_color)
            run_color, run_lo, run_hi = c, lo, hi
        if run_color is not None:
            batch.add(run_lo, run_hi, off0, off1, run_color)
        batch.flush(sink)

        # Inside the compositor the header row is solved for the whole stack at
        # once, so a caption wider than its own column is turned or staggered
        # rather than laid across its neighbour's.  A track drawn on its own
        # has no stack and no neighbour, so it still captions itself.
        if self.data.rows and self.opt("show_title", True) and self.title \
                and not compositor_owns_titles(ctx):
            size = float(self.opt("title_size") or ctx.theme.track_title_size)
            place = ctx.projector.text(-0.7, (off0 + off1) * 0.5, Anchor.MIDDLE)
            style = TextStyle(family=ctx.theme.font_family, size=size,
                              color=ctx.theme.muted, anchor=place.anchor,
                              baseline=Baseline.MIDDLE)
            sink.add(TextMark(x=place.x, y=place.y, text=self.title,
                              style=style, rotation=place.rotation))

    def legend(self) -> Legend:
        ramp = self.ramp()
        items = [LegendItem(label=self.title or "value", shape="gradient",
                            color=ramp.at(1.0),
                            gradient=ramp.sample(int(self.opt("legend_samples", 24))),
                            value_range=ramp.domain)]
        miss = self._missing_color()
        if miss is not None:
            items.append(LegendItem(label=str(self.opt("missing_label", "no value")),
                                    color=miss, shape="square"))
        return Legend(title=self.title, items=items, kind="continuous")

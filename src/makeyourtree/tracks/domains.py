# SPDX-License-Identifier: MIT
"""Sequence architecture: a scaled backbone per tip carrying shaped features.

Each record is one sequence -- its total length, then any number of features
with a start, an end, a shape, a colour and a label.  The backbone length is
``length / longest_length`` of the track's thickness, so the *scale is global*:
two rows may be compared directly, which is the entire point of drawing the
diagrams side by side.  Feature coordinates are residue positions, 1-based and
inclusive, and are clipped to the backbone rather than allowed to overhang it;
annotation files routinely carry a feature that runs past the stated length,
and a shape floating beyond the end of its own sequence is a lie.

Geometry lives in band space and every vertex goes through the projector, so a
feature is a polygon in a rectangular layout and the same polygon warped into
an annular sector in a polar one.  The warping is why edges are resampled
before projection (see :func:`makeyourtree.tracks.bars.project_polyline`): a
straight band-space edge spanning several rows is an arc once projected, and a
two-point edge would cut the corner off every shape in the ring.

The outlines are defined here rather than taken from
:data:`makeyourtree.tracks.shapes.SHAPES`, and the reason is geometric: those are
*symbols* -- a constant scene size centred on one band point -- while a feature
has to span the residue range it annotates, which is an arbitrary quad.  A
symbol builder cannot express that.  What the shared registry does supply is
the legend swatch: :func:`legend_shape` maps each feature outline onto the
nearest registered symbol so the key beside the figure is drawn by the same
code as every other track's key.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from ..scene.marks import (Anchor, Baseline, MarkSink, Paint, PolygonMark,
                           TextMark, TextStyle)
from ..style.color import Color
from .bars import (add_quad, iter_band_rows, numeric, option_color,
                   project_polyline, safe_color)
from .base import Legend, LegendItem, Track, TrackContext, register
from .shapes import SHAPES, QuadBatch

__all__ = ["DomainArchitectureTrack", "DomainFeature", "parse_feature",
           "shape_outline", "legend_shape", "SHAPE_NAMES"]


@dataclass(frozen=True, slots=True)
class DomainFeature:
    """One feature in residue coordinates, 1-based and inclusive."""

    start: float
    end: float
    shape: str = "rect"
    color: Color | None = None
    label: str = ""

    def clipped(self, length: float) -> "DomainFeature | None":
        """The part of the feature that lies on a sequence of *length*."""
        lo = max(0.0, min(self.start, self.end) - 1.0)
        hi = min(float(length), max(self.start, self.end))
        if hi <= lo:
            return None
        return DomainFeature(lo + 1.0, hi, self.shape, self.color, self.label)


_ALIASES: dict[str, str] = {
    "rectangle": "rect", "box": "rect", "bar": "rect",
    "hex": "hexagon", "hexagon-h": "hexagon",
    "oval": "ellipse", "circle": "ellipse",
    "rhombus": "diamond", "square": "rect",
    "triangle": "triangle-right", "arrow": "arrow-right",
    "pentagon": "pentagon-up",
    "octagonal": "octagon", "spacer": "gap",
}

SHAPE_NAMES: tuple[str, ...] = (
    "rect", "hexagon", "hexagon-v", "ellipse", "diamond",
    "triangle-right", "triangle-left", "arrow-right", "arrow-left",
    "pentagon-up", "pentagon-down", "octagon", "gap",
)
"""Feature outlines this track knows how to draw, by our own names."""


def canonical_shape(name: Any) -> str:
    key = str(name or "rect").strip().lower()
    key = _ALIASES.get(key, key)
    return key if key in SHAPE_NAMES else "rect"


def parse_feature(raw: Any) -> DomainFeature | None:
    """One feature from a mapping, a sequence, or a delimited string.

    The string form is ``start|end|shape|colour|label``; trailing fields may be
    omitted.  Anything without a usable numeric start and end is dropped, since
    a feature with no position has nowhere to go.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, DomainFeature):
        return raw
    if isinstance(raw, dict):
        fields = [raw.get("start"), raw.get("end"), raw.get("shape"),
                  raw.get("color", raw.get("colour")), raw.get("label")]
    elif isinstance(raw, (list, tuple)):
        fields = list(raw[:5]) + [None] * (5 - len(raw[:5]))
    else:
        text = str(raw)
        parts = text.split("|") if "|" in text else text.split(":")
        fields = [p.strip() for p in parts[:5]] + [None] * (5 - len(parts[:5]))
    start, end = numeric(fields[0]), numeric(fields[1])
    if start is None or end is None:
        return None
    color = None
    if fields[3] not in (None, ""):
        color = safe_color(fields[3], Color(120, 120, 130))
    return DomainFeature(start, end, canonical_shape(fields[2]), color,
                         str(fields[4]) if fields[4] not in (None, "") else "")


# ------------------------------------------------------------------ shapes

BandPoints = list[tuple[float, float]]
Builder = Callable[[float, float, float, float], BandPoints]


def _rect(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    return [(r0, o0), (r1, o0), (r1, o1), (r0, o1)]


def _notch(r0: float, r1: float, o0: float, o1: float) -> float:
    """Corner inset used by the pointed shapes: never more than half of either
    dimension, so a short feature degenerates gracefully instead of inverting."""
    return min((o1 - o0) * 0.5, (r1 - r0) * 0.5)


def _hexagon(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    n = _notch(r0, r1, o0, o1)
    mid = (r0 + r1) * 0.5
    return [(r0, o0 + n), (r0, o1 - n), (mid, o1), (r1, o1 - n), (r1, o0 + n), (mid, o0)]


def _hexagon_v(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    n = _notch(r0, r1, o0, o1)
    mid = (o0 + o1) * 0.5
    return [(r0 + n, o0), (r0, mid), (r0 + n, o1), (r1 - n, o1), (r1, mid), (r1 - n, o0)]


def _ellipse(r0: float, r1: float, o0: float, o1: float, steps: int = 32) -> BandPoints:
    cr, co = (r0 + r1) * 0.5, (o0 + o1) * 0.5
    ar, ao = (r1 - r0) * 0.5, (o1 - o0) * 0.5
    return [(cr + ar * math.sin(2 * math.pi * i / steps),
             co + ao * math.cos(2 * math.pi * i / steps)) for i in range(steps)]


def _diamond(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    cr, co = (r0 + r1) * 0.5, (o0 + o1) * 0.5
    return [(cr, o0), (r0, co), (cr, o1), (r1, co)]


def _triangle_right(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    return [(r0, o0), (r1, o0), ((r0 + r1) * 0.5, o1)]


def _triangle_left(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    return [(r0, o1), (r1, o1), ((r0 + r1) * 0.5, o0)]


def _arrow_right(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    n = _notch(r0, r1, o0, o1)
    return [(r0, o0), (r0, o1 - n), ((r0 + r1) * 0.5, o1), (r1, o1 - n), (r1, o0)]


def _arrow_left(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    n = _notch(r0, r1, o0, o1)
    return [(r0, o1), (r0, o0 + n), ((r0 + r1) * 0.5, o0), (r1, o0 + n), (r1, o1)]


def _pentagon_up(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    n = _notch(r0, r1, o0, o1)
    mid = (o0 + o1) * 0.5
    return [(r1, o0), (r0 + n, o0), (r0, mid), (r0 + n, o1), (r1, o1)]


def _pentagon_down(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    n = _notch(r0, r1, o0, o1)
    mid = (o0 + o1) * 0.5
    return [(r0, o0), (r1 - n, o0), (r1, mid), (r1 - n, o1), (r0, o1)]


def _octagon(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    c = min(o1 - o0, r1 - r0) * 0.3
    return [(r0 + c, o0), (r0, o0 + c), (r0, o1 - c), (r0 + c, o1),
            (r1 - c, o1), (r1, o1 - c), (r1, o0 + c), (r1 - c, o0)]


def _gap(r0: float, r1: float, o0: float, o1: float) -> BandPoints:
    """A break in the sequence: same span, a third of the height."""
    inset = (r1 - r0) / 3.0
    return _rect(r0 + inset, r1 - inset, o0, o1)


_LOCAL_SHAPES: dict[str, Builder] = {
    "rect": _rect, "hexagon": _hexagon, "hexagon-v": _hexagon_v,
    "ellipse": _ellipse, "diamond": _diamond,
    "triangle-right": _triangle_right, "triangle-left": _triangle_left,
    "arrow-right": _arrow_right, "arrow-left": _arrow_left,
    "pentagon-up": _pentagon_up, "pentagon-down": _pentagon_down,
    "octagon": _octagon, "gap": _gap,
}


_LEGEND_SHAPE: dict[str, str] = {
    "rect": "square", "hexagon": "hexagon", "hexagon-v": "hexagon",
    "ellipse": "ellipse", "diamond": "diamond",
    "triangle-right": "triangle", "triangle-left": "triangle",
    "arrow-right": "arrow-right", "arrow-left": "arrow-left",
    "pentagon-up": "pentagon", "pentagon-down": "pentagon",
    "octagon": "hexagon", "gap": "square",
}


def legend_shape(name: str) -> str:
    """The registered symbol that stands in for a feature outline in a legend.

    Legends draw constant-size glyphs, which is exactly what
    :data:`makeyourtree.tracks.shapes.SHAPES` provides, so the mapping goes to a
    registered name and falls back to a square if the registry ever loses one.
    """
    mapped = _LEGEND_SHAPE.get(name, "square")
    return mapped if mapped in SHAPES else "square"


def shape_outline(name: str, row0: float, row1: float, off0: float,
                  off1: float) -> BandPoints:
    """Band-space outline of *name* filling the quad ``[row0, row1] x [off0, off1]``."""
    return _LOCAL_SHAPES.get(name, _rect)(row0, row1, off0, off1)


# ------------------------------------------------------------------- track


@register
class DomainArchitectureTrack(Track):
    """A scaled sequence backbone per tip with shaped features drawn on it."""

    type_id = "domain-architecture"
    display_name = "Domain architecture"
    multi_column = True

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        opts = super().default_options()
        opts.update({
            "thickness": 160.0,
            "length_column": 0,
            "backbone_color": None,
            "backbone_height": 0.18,
            "feature_height": 0.72,
            "show_labels": True,
            "label_size": None,
            "label_padding": 3.0,
            "min_feature_width": 1.0,
            "show_internal": False,
        })
        return opts

    # -------------------------------------------------------------- shape

    def measure(self, ctx: TrackContext) -> float:
        return max(0.0, float(self.opt("thickness", 160.0)))

    def _length_column(self) -> int:
        raw = self.opt("length_column", 0)
        if isinstance(raw, str):
            try:
                return self.data.columns.index(raw)
            except ValueError:
                return 0
        return int(raw or 0)

    def sequence_length(self, node_id: int) -> float | None:
        return numeric(self.data.get(node_id, self._length_column()))

    def features(self, node_id: int) -> list[DomainFeature]:
        """Every parseable feature on one node, in file order."""
        row = self.data.rows.get(node_id)
        if not row:
            return []
        skip = self._length_column()
        out: list[DomainFeature] = []
        for i, cell in enumerate(row):
            if i == skip:
                continue
            feature = parse_feature(cell)
            if feature is not None:
                out.append(feature)
        return out

    def max_length(self) -> float:
        values = self.data.numeric_column(self._length_column())
        return max(values) if values else 0.0

    # --------------------------------------------------------------- draw

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        longest = self.max_length()
        if longest <= 0:
            return
        scale = self.measure(ctx) / longest
        theme = ctx.theme
        backbone_color = option_color(self, "backbone_color", theme.guide_color)
        opacity = float(self.opt("opacity", 1.0) or 1.0)
        stroke = (option_color(self, "border_color", theme.foreground)
                  if self.opt("border_color") is not None else None)
        stroke_w = float(self.opt("border_width", 0.0) or 0.0)

        spine = QuadBatch(ctx.projector, opacity=opacity)
        back_half = max(0.02, float(self.opt("backbone_height", 0.18) or 0.18)) * 0.5
        feat_half = min(max(float(self.opt("feature_height", 0.72) or 0.72),
                            0.05), 1.0) * 0.5
        default_fill = theme.accent
        labels: list[TextMark] = []

        for nid, centre, extent in iter_band_rows(
                ctx, self.data, bool(self.opt("show_internal", False))):
            length = self.sequence_length(nid)
            if length is None or length <= 0:
                continue
            bar_end = ctx.offset + length * scale
            add_quad(spine, centre - extent * back_half,
                     centre + extent * back_half, ctx.offset, bar_end,
                     backbone_color)
            row0 = centre - extent * feat_half
            row1 = centre + extent * feat_half
            for feature in self.features(nid):
                clipped = feature.clipped(length)
                if clipped is None:
                    continue
                off0 = ctx.offset + (clipped.start - 1.0) * scale
                off1 = min(bar_end, ctx.offset + clipped.end * scale)
                if off1 - off0 < float(self.opt("min_feature_width", 1.0) or 0.0):
                    off1 = min(bar_end, off0 + float(self.opt("min_feature_width", 1.0) or 0.0))
                if off1 <= off0:
                    continue
                fill = clipped.color or default_fill
                points = shape_outline(clipped.shape, row0, row1, off0, off1)
                flat = project_polyline(ctx.projector, points + points[:1])
                sink.add(PolygonMark(
                    paint=Paint(fill=fill, stroke=stroke, width=stroke_w,
                                opacity=opacity),
                    tag=nid, points=tuple(flat[:-2])))
                mark = self._label_mark(ctx, clipped, fill, centre, extent,
                                        off0, off1)
                if mark is not None:
                    labels.append(mark)
        spine.flush(sink)
        for mark in labels:
            sink.add(mark)

    def _label_mark(self, ctx: TrackContext, feature: DomainFeature, fill: Color,
                    centre: float, extent: float, off0: float,
                    off1: float) -> TextMark | None:
        """A feature label, but only when it genuinely fits inside the shape.

        The along-band budget is the feature's own offset span; the across-band
        budget is one row's scene width at that offset times the rows the row
        occupies.  Both come from the projector, so the same test works in a
        ring, where a feature near the centre is physically narrower than the
        identical feature further out.
        """
        if not feature.label or not self.opt("show_labels", True):
            return None
        size = float(self.opt("label_size") or ctx.theme.track_title_size)
        pad = float(self.opt("label_padding", 3.0) or 0.0)
        along = (off1 - off0) - 2 * pad
        across = ctx.projector.tangential((off0 + off1) * 0.5) * extent
        if along <= 0 or across < ctx.metrics.line_height(size):
            return None
        if ctx.metrics.advance(feature.label, size) > along:
            return None
        place = ctx.projector.text(centre, (off0 + off1) * 0.5, Anchor.MIDDLE)
        style = TextStyle(family=ctx.theme.font_family, size=size,
                          color=fill.readable_text(), anchor=place.anchor,
                          baseline=Baseline.MIDDLE)
        return TextMark(paint=Paint(), x=place.x, y=place.y, text=feature.label,
                        style=style, rotation=place.rotation, max_width=along)

    # ------------------------------------------------------------- legend

    def legend(self) -> Legend:
        """One entry per feature family, keyed on label, shape and colour.

        Families, not occurrences: the same domain appears on dozens of rows
        and the reader needs the key once.
        """
        seen: dict[tuple[str, str, str], LegendItem] = {}
        for nid in self.data.rows:
            for feature in self.features(nid):
                if not feature.label:
                    continue
                color = feature.color
                key = (feature.label, feature.shape, color.hex if color else "")
                seen.setdefault(key, LegendItem(label=feature.label, color=color,
                                                shape=legend_shape(feature.shape)))
        items = [seen[k] for k in sorted(seen)]
        return Legend(title=self.title, items=items)

# SPDX-License-Identifier: MIT
"""Clade range: a coloured wash behind a whole clade.

The track paints into :attr:`~makeyourtree.scene.marks.Layer.UNDERLAY` rather than
into ``TRACKS``.  A range is background, not data drawn beside the tree: it
covers the same ground as the branches it is describing, so it has to go down
before them or it hides the topology it is meant to annotate.  Pale fills at
low opacity are the default for the same reason.

A range consumes no stack width -- :meth:`CladeRangeTrack.measure` returns
zero -- because it grows *inward* over the tree body rather than outward past
the labels.  Reaching inward is the one thing band space does not give a track
for free, so the inner edge comes from
:func:`~makeyourtree.tracks.shapes.band_offset_of`, which recovers a node's offset
by projecting its scene position onto the outward ray at its own row.  That
works in every layout mode without asking which one is in force.
"""

from __future__ import annotations

from typing import Any

from ..scene.marks import (Anchor, Baseline, Layer, MarkSink, TextMark,
                           TextStyle)
from ..style.color import Color, parse_color
from .base import Legend, LegendItem, Track, TrackContext, register
from .shapes import QuadBatch, band_offset_of

__all__ = ["CladeRangeTrack"]


def _column(data, name: str, fallback: int) -> int:
    """Index of a named column, or *fallback* when the table is unnamed."""
    for i, c in enumerate(data.columns):
        if str(c).strip().lower() == name:
            return i
    return fallback


@register
class CladeRangeTrack(Track):
    """A background wash spanning a clade's rows and the depth of the tree."""

    type_id = "clade-range"
    display_name = "Clade range"
    default_layer = Layer.UNDERLAY

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        o = super().default_options()
        o.update({
            "opacity": 0.28,
            "cover": "clade",
            "extend": 0.0,
            "inner_offset": None,
            "row_shrink": 0.0,
            "show_labels": True,
            "label_position": "outer",
            "label_size": None,
            "label_color": None,
            "label_rotation": 0.0,
        })
        return o

    # ---------------------------------------------------------------- data

    def _color_of(self, node_id: int) -> Color | None:
        spec = self.data.get(node_id, _column(self.data, "color", 0))
        if spec is None or spec == "":
            return None
        try:
            return parse_color(spec)
        except ValueError:
            return None

    def _label_of(self, node_id: int) -> str:
        idx = _column(self.data, "label", 1)
        v = self.data.get(node_id, idx)
        return "" if v is None else str(v)

    def _inner_offset(self, ctx: TrackContext, node_id: int) -> float:
        override = self.opt("inner_offset")
        if override is not None:
            return float(override)
        anchor = node_id if self.opt("cover", "clade") == "clade" else ctx.tree.root.id
        if not ctx.frame.has(anchor):
            anchor = node_id
        return band_offset_of(ctx.frame, ctx.projector, anchor)

    # ------------------------------------------------------------ protocol

    def measure(self, ctx: TrackContext) -> float:
        return 0.0

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        outer = ctx.offset + float(self.opt("extend", 0.0))
        shrink = float(self.opt("row_shrink", 0.0))
        border = self.opt("border_color")
        batch = QuadBatch(
            ctx.projector, opacity=float(self.opt("opacity", 0.28)),
            stroke=parse_color(border) if border else None,
            stroke_width=float(self.opt("border_width", 0.0)))
        labels: list[tuple[float, float, str, Color]] = []

        for node_id in self.data.rows:
            if not ctx.frame.has(node_id):
                continue
            color = self._color_of(node_id)
            if color is None:
                continue
            lo, hi = ctx.rows_of(node_id)
            if hi - lo <= 2 * shrink:
                shrink_here = 0.0
            else:
                shrink_here = shrink
            lo, hi = lo + shrink_here, hi - shrink_here
            inner = self._inner_offset(ctx, node_id)
            if inner >= outer:
                continue
            batch.add(lo, hi, inner, outer, color)
            text = self._label_of(node_id)
            if text and self.opt("show_labels", True):
                labels.append(((lo + hi) * 0.5,
                               self._label_offset(inner, outer), text, color))
        batch.flush(sink, self.default_layer)

        for row, offset, text, color in labels:
            self._draw_label(ctx, sink, row, offset, text, color)

    def _label_offset(self, inner: float, outer: float) -> float:
        pos = str(self.opt("label_position", "outer"))
        if pos == "inner":
            return inner
        if pos == "center":
            return (inner + outer) * 0.5
        return outer

    def _draw_label(self, ctx: TrackContext, sink: MarkSink, row: float,
                    offset: float, text: str, fill: Color) -> None:
        pos = str(self.opt("label_position", "outer"))
        align = Anchor.MIDDLE if pos == "center" else (
            Anchor.START if pos == "inner" else Anchor.END)
        place = ctx.projector.text(row, offset, align, rotate=True)
        spec = self.opt("label_color")
        try:
            color = parse_color(spec) if spec else fill.darken(0.45)
        except ValueError:
            color = fill.darken(0.45)
        style = TextStyle(family=ctx.theme.font_family,
                          size=float(self.opt("label_size")
                                     or ctx.theme.track_title_size),
                          color=color, anchor=place.anchor,
                          baseline=Baseline.MIDDLE)
        sink.add(TextMark(x=place.x, y=place.y, text=text, style=style,
                          rotation=place.rotation
                          + float(self.opt("label_rotation", 0.0))),
                 self.default_layer)

    def legend(self) -> Legend:
        seen: set[tuple[str, str]] = set()
        items: list[LegendItem] = []
        for node_id in self.data.rows:
            color = self._color_of(node_id)
            if color is None:
                continue
            label = self._label_of(node_id) or str(node_id)
            key = (label, color.hex)
            if key in seen:
                continue
            seen.add(key)
            items.append(LegendItem(label=label, color=color, shape="square"))
        return Legend(title=self.title, items=items, kind="categorical")

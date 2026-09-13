# SPDX-License-Identifier: MIT
"""Binary matrix: a presence/absence symbol grid.

Presence, absence and *no data* are three different statements and get three
different renderings: a filled symbol, an outlined symbol, and nothing at all.
Collapsing the last two -- drawing an empty box for both "we looked and it is
not there" and "we never looked" -- is the single most common way a
presence/absence figure misleads, so the outline is reserved for a real
negative and a missing cell simply leaves the grid empty.

Symbols keep a constant size in scene units and are drawn through
:mod:`makeyourtree.tracks.shapes`, so they stay circles and stars in a circular
layout instead of being warped into annular wedges.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..scene.marks import (Anchor, Baseline, Cap, Join, MarkSink, Paint,
                           PathMark, TextMark, TextStyle)
from ..style.color import Color, parse_color
from .base import Legend, LegendItem, Track, TrackContext, register
from .shapes import is_open_shape, shape_path
from .strip import palette_colors

__all__ = ["BinaryMatrixTrack", "PRESENT", "ABSENT", "UNKNOWN"]

PRESENT = 1
ABSENT = 0
UNKNOWN = -1

_TRUE = frozenset({"1", "true", "yes", "y", "t", "+", "present", "on"})
_FALSE = frozenset({"0", "false", "no", "n", "f", "-0", "absent", "off"})


def classify(value: Any) -> int:
    """Map a cell to :data:`PRESENT`, :data:`ABSENT` or :data:`UNKNOWN`.

    Lenient by design: tables in the wild spell presence as ``1``, ``yes``,
    ``TRUE`` and ``+``.  Anything unrecognised is unknown rather than absent,
    because guessing "absent" invents a negative observation.
    """
    if value is None:
        return UNKNOWN
    if isinstance(value, bool):
        return PRESENT if value else ABSENT
    if isinstance(value, (int, float)):
        if value == 1:
            return PRESENT
        if value == 0:
            return ABSENT
        return UNKNOWN
    s = str(value).strip().lower()
    if not s or s == "-":
        return UNKNOWN
    if s in _TRUE:
        return PRESENT
    if s in _FALSE:
        return ABSENT
    return UNKNOWN


@register
class BinaryMatrixTrack(Track):
    """A symbol per (tip, column) cell showing presence or absence."""

    type_id = "binary-matrix"
    display_name = "Binary matrix"
    multi_column = True

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        o = super().default_options()
        o.update({
            "cell_size": 20.0,
            "symbol_scale": 0.72,
            "margin": 0.0,
            "shape": "square",
            "column_shapes": None,
            "color": None,
            "column_colors": None,
            "palette": None,
            "outline_width": 0.0,
            "column_labels": True,
            "label_size": None,
            "label_rotation": -90.0,
            "show_absent": True,
        })
        return o

    # ------------------------------------------------------------- columns

    def column_count(self) -> int:
        if self.data.columns:
            return len(self.data.columns)
        return max((len(r) for r in self.data.rows.values()), default=0)

    def column_name(self, index: int) -> str:
        if index < len(self.data.columns):
            return str(self.data.columns[index])
        return f"col{index + 1}"

    def column_shape(self, index: int) -> str:
        shapes: Sequence[str] | None = self.opt("column_shapes")
        if shapes and index < len(shapes):
            return str(shapes[index])
        return str(self.opt("shape", "square"))

    def column_colors(self) -> list[Color]:
        """One colour per column: explicit list, single colour, or the palette."""
        n = self.column_count()
        explicit: Sequence[Any] | None = self.opt("column_colors")
        single = self.opt("color")
        pal = palette_colors(self.opt("palette"))
        out: list[Color] = []
        for i in range(n):
            spec = None
            if explicit and i < len(explicit):
                spec = explicit[i]
            elif single is not None:
                spec = single
            if spec is None:
                out.append(pal[i % len(pal)])
                continue
            try:
                out.append(parse_color(spec))
            except ValueError:
                out.append(pal[i % len(pal)])
        return out

    # ------------------------------------------------------------ protocol

    def measure(self, ctx: TrackContext) -> float:
        return (float(self.opt("margin", 0.0))
                + self.column_count() * float(self.opt("cell_size", 20.0)))

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        n = self.column_count()
        if not n:
            return
        colors = self.column_colors()
        cell = float(self.opt("cell_size", 20.0))
        base = ctx.offset + float(self.opt("margin", 0.0))
        scale = float(self.opt("symbol_scale", 0.72))
        opacity = float(self.opt("opacity", 1.0))
        show_absent = bool(self.opt("show_absent", True))

        for nid in ctx.tip_ids():
            row = self.data.rows.get(nid)
            if row is None:
                continue
            lo, hi = ctx.rows_of(nid)
            mid = (lo + hi) * 0.5
            for c in range(n):
                state = classify(row[c]) if c < len(row) else UNKNOWN
                if state == UNKNOWN or (state == ABSENT and not show_absent):
                    continue
                off = base + (c + 0.5) * cell
                # A symbol must fit both its column and its row; in a polar
                # layout the row's scene width grows with radius, so ask the
                # projector rather than assuming the linear answer.
                size = min(cell, ctx.projector.tangential(off) * (hi - lo)) * scale
                if size <= 0:
                    continue
                self._emit(sink, ctx, self.column_shape(c), mid, off, size,
                           colors[c], state == PRESENT, opacity, nid)

        if self.opt("column_labels", True):
            self._draw_column_labels(ctx, sink, base, cell)

    def _emit(self, sink: MarkSink, ctx: TrackContext, shape: str, row: float,
              offset: float, size: float, color: Color, filled: bool,
              opacity: float, tag: int) -> None:
        segs = shape_path(shape, row, offset, size, ctx.projector)
        width = float(self.opt("outline_width", 0.0)) or max(1.0, size * 0.12)
        if filled and not is_open_shape(shape):
            paint = Paint(fill=color, opacity=opacity)
        else:
            paint = Paint(fill=None, stroke=color, width=width, cap=Cap.ROUND,
                          join=Join.ROUND, opacity=opacity)
        sink.add(PathMark(paint=paint, segments=segs, tag=tag))

    def _draw_column_labels(self, ctx: TrackContext, sink: MarkSink,
                            base: float, cell: float) -> None:
        size = float(self.opt("label_size") or ctx.theme.track_title_size)
        rot = float(self.opt("label_rotation", -90.0))
        for c in range(self.column_count()):
            name = self.column_name(c)
            if not name:
                continue
            place = ctx.projector.text(-0.3, base + (c + 0.5) * cell,
                                       Anchor.START, rotate=True)
            style = TextStyle(family=ctx.theme.font_family, size=size,
                              color=ctx.theme.muted, anchor=place.anchor,
                              baseline=Baseline.MIDDLE)
            sink.add(TextMark(x=place.x, y=place.y, text=name, style=style,
                              rotation=place.rotation + rot))

    def legend(self) -> Legend:
        colors = self.column_colors()
        items = [LegendItem(label=self.column_name(c), color=colors[c],
                            shape=self.column_shape(c))
                 for c in range(self.column_count())]
        return Legend(title=self.title, items=items, kind="categorical")

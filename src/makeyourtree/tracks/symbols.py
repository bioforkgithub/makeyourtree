# SPDX-License-Identifier: MIT
"""Symbols: a shape per tip or per internal node, sized and coloured by value.

Area, not radius, is what a reader takes from a symbol's size (Stevens' power
law puts the perceived magnitude of an area at roughly its 0.7 power, and of a
length at nearly 1.0, so a radius-linear encoding exaggerates large values by
about the square).  ``size_mode`` therefore defaults to ``sqrt``: the drawn
diameter is proportional to the square root of the value, which makes the area
proportional to the value itself.  ``linear`` is available for compatibility
with tables authored against a radius-linear tool, and it is the caller's
decision to make, not a silent one.

Symbols are constant-size in scene units and are built by
:mod:`makeyourtree.tracks.shapes`, so a star stays a star in a circular layout
while still pointing consistently away from the tree.
"""

from __future__ import annotations

import math
from typing import Any

from ..scene.marks import Cap, Join, MarkSink, Paint, PathMark
from ..style.color import Color, parse_color
from .base import Legend, LegendItem, Track, TrackContext, register
from .gradient import to_float
from .shapes import band_offset_of, is_open_shape, shape_path
from .strip import CategoryColors, palette_colors

__all__ = ["SymbolTrack"]


@register
class SymbolTrack(Track):
    """A shape per node, sized by one column and coloured by another."""

    type_id = "symbols"
    display_name = "Symbols"

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        o = super().default_options()
        o.update({
            "shape": "circle",
            "shape_column": None,
            "max_size": 14.0,
            "min_size": 2.0,
            "size_mode": "sqrt",
            "size_column": None,
            "color": None,
            "color_column": None,
            "palette": None,
            "colors": {},
            "fill": True,
            "stroke": None,
            "stroke_width": 0.0,
            "margin": 4.0,
            "at_nodes": False,
            "position": 1.0,
            "legend_steps": 3,
            "legend_format": "{:.3g}",
        })
        return o

    # -------------------------------------------------------------- values

    def _size_domain(self) -> float:
        col = self.opt("size_column")
        if col is None:
            return 0.0
        vals = self.data.numeric_column(int(col))
        return max((abs(v) for v in vals), default=0.0)

    def _size_of(self, node_id: int, vmax: float) -> float | None:
        """Drawn diameter, or None when the row carries no usable magnitude."""
        max_size = float(self.opt("max_size", 14.0))
        col = self.opt("size_column")
        if col is None:
            return max_size
        v = to_float(self.data.get(node_id, int(col)))
        if v is None:
            return None
        if vmax <= 0:
            return max_size
        frac = min(1.0, abs(v) / vmax)
        if str(self.opt("size_mode", "sqrt")) == "linear":
            size = max_size * frac
        else:
            size = max_size * math.sqrt(frac)
        return max(float(self.opt("min_size", 2.0)), size)

    def _scale(self, ctx: TrackContext | None = None) -> CategoryColors | None:
        col = self.opt("color_column")
        if col is None:
            return None
        theme_palette = ctx.theme.categorical_palette if ctx is not None else None
        return CategoryColors(
            self.data.categories(int(col)),
            explicit=self.opt("colors") or {},
            palette=palette_colors(self.opt("palette") or theme_palette))

    def _color_of(self, node_id: int, scale: CategoryColors | None,
                  default: Color) -> Color:
        if scale is None:
            return default
        c = scale.color(self.data.get(node_id, int(self.opt("color_column"))))
        return c if c is not None else default

    def _shape_of(self, node_id: int) -> str:
        col = self.opt("shape_column")
        if col is not None:
            v = self.data.get(node_id, int(col))
            if v:
                return str(v)
        return str(self.opt("shape", "circle"))

    # ------------------------------------------------------------ protocol

    def measure(self, ctx: TrackContext) -> float:
        if self.opt("at_nodes", False):
            # Node symbols sit on the branches, inside the tree body: they take
            # no room in the outward stack.
            return 0.0
        return float(self.opt("margin", 4.0)) + float(self.opt("max_size", 14.0))

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        vmax = self._size_domain()
        scale = self._scale(ctx)
        default = self._default_color(ctx)
        at_nodes = bool(self.opt("at_nodes", False))
        opacity = float(self.opt("opacity", 1.0))
        column_offset = (ctx.offset + float(self.opt("margin", 4.0))
                         + float(self.opt("max_size", 14.0)) * 0.5)
        fraction = min(1.0, max(0.0, float(self.opt("position", 1.0))))

        for node_id in self._targets(ctx, at_nodes):
            size = self._size_of(node_id, vmax)
            if size is None or size <= 0:
                continue
            if at_nodes:
                row = ctx.frame.row(node_id)
                offset = self._branch_offset(ctx, node_id, fraction)
            else:
                lo, hi = ctx.rows_of(node_id)
                row, offset = (lo + hi) * 0.5, column_offset
            shape = self._shape_of(node_id)
            self._emit(sink, ctx, shape, row, offset, size,
                       self._color_of(node_id, scale, default), opacity, node_id)

    def _targets(self, ctx: TrackContext, at_nodes: bool) -> list[int]:
        """Node ids to draw on, in a stable order.

        Tips come from the frame so the drawing order matches the rows; node
        symbols come from the data, filtered to nodes the layout actually
        placed, because an annotated node may be inside a collapsed clade.
        """
        if not at_nodes:
            return [nid for nid in ctx.tip_ids() if nid in self.data.rows]
        return [nid for nid in self.data.rows if ctx.frame.has(nid)]

    def _branch_offset(self, ctx: TrackContext, node_id: int,
                       fraction: float) -> float:
        """Offset of a point *fraction* of the way along the node's own branch."""
        own = band_offset_of(ctx.frame, ctx.projector, node_id)
        if fraction >= 1.0:
            return own
        node = ctx.tree.by_id(node_id)
        parent = node.parent if node is not None else None
        if parent is None or not ctx.frame.has(parent.id):
            return own
        start = band_offset_of(ctx.frame, ctx.projector, parent.id)
        return start + (own - start) * fraction

    def _default_color(self, ctx: TrackContext) -> Color:
        spec = self.opt("color")
        if spec is None:
            return ctx.theme.accent
        try:
            return parse_color(spec)
        except ValueError:
            return ctx.theme.accent

    def _emit(self, sink: MarkSink, ctx: TrackContext, shape: str, row: float,
              offset: float, size: float, color: Color, opacity: float,
              tag: int) -> None:
        segs = shape_path(shape, row, offset, size, ctx.projector)
        stroke_spec = self.opt("stroke")
        stroke = None
        if stroke_spec is not None:
            try:
                stroke = parse_color(stroke_spec)
            except ValueError:
                stroke = None
        filled = bool(self.opt("fill", True)) and not is_open_shape(shape)
        width = float(self.opt("stroke_width", 0.0))
        if not filled:
            stroke = stroke or color
            width = width or max(1.0, size * 0.12)
        paint = Paint(fill=color if filled else None, stroke=stroke,
                      width=width, cap=Cap.ROUND, join=Join.ROUND,
                      opacity=opacity)
        sink.add(PathMark(paint=paint, segments=segs, tag=tag))

    # -------------------------------------------------------------- legend

    def legend(self) -> Legend:
        scale = self._scale()
        shape = str(self.opt("shape", "circle"))
        if scale is not None:
            items = [LegendItem(label=name, color=color, shape=shape)
                     for name, color in scale.items()]
            if items:
                return Legend(title=self.title, items=items, kind="categorical")
        if self.opt("size_column") is not None:
            return self._size_legend(shape)
        color = self.opt("color")
        try:
            swatch = parse_color(color) if color else None
        except ValueError:
            swatch = None
        label = self.title or self.display_name
        return Legend(title=self.title,
                      items=[LegendItem(label=label, color=swatch, shape=shape)],
                      kind="categorical")

    def _size_legend(self, shape: str) -> Legend:
        """Three reference magnitudes, spaced so their *diameters* step evenly.

        Under the sqrt encoding that means values in geometric quarters -- the
        drawn sizes are then max, half and a quarter, which is what a stacked
        size key needs in order to be readable.
        """
        vmax = self._size_domain()
        if vmax <= 0:
            return Legend(title=self.title, items=[], kind="scale")
        steps = max(2, int(self.opt("legend_steps", 3)))
        fmt = str(self.opt("legend_format", "{:.3g}"))
        linear = str(self.opt("size_mode", "sqrt")) == "linear"
        items: list[LegendItem] = []
        for k in range(steps):
            frac = (0.5 ** k) if linear else (0.25 ** k)
            v = vmax * frac
            items.append(LegendItem(label=fmt.format(v), shape=shape,
                                    value_range=(v, v)))
        return Legend(title=self.title, items=items, kind="scale")

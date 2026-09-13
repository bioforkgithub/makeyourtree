# SPDX-License-Identifier: MIT
"""External text labels: a second caption per tip, outside the tree.

The whole track is one detail: placement goes through
:meth:`~makeyourtree.layout.projector.Projector.text`, never through
:meth:`~makeyourtree.layout.projector.Projector.point`.  In a circular layout the
projector rotates each label to follow its radius and, on the left half of the
fan, turns it a further 180 degrees and mirrors its anchor so it still reads
left-to-right.  Doing that here, per mode, would be the one conditional that
the band-space contract exists to avoid -- and getting it wrong leaves half the
figure upside down.

``rotation`` is measured from the outward direction, so it means the same thing
in every layout: 0 follows the radius (or the x axis), -90 runs across the band.
"""

from __future__ import annotations

from typing import Any

from ..scene.marks import Anchor, Baseline, MarkSink, TextMark, TextStyle
from ..style.color import Color, parse_color
from .base import Legend, Track, TrackContext, register

__all__ = ["TextLabelTrack"]

_ANCHORS = {"start": Anchor.START, "middle": Anchor.MIDDLE, "end": Anchor.END}


@register
class TextLabelTrack(Track):
    """One line of text per tip, in its own column beside the tree."""

    type_id = "text-labels"
    display_name = "Text labels"

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        o = super().default_options()
        o.update({
            "margin": 4.0,
            "size": None,
            "color": None,
            "bold": False,
            "italic": False,
            "align": "start",
            "rotation": 0.0,
            "rotate_with_layout": True,
            "letter_spacing": 0.0,
            "max_width": None,
            "column": 0,
            "color_column": None,
            "ellipsize": True,
        })
        return o

    # -------------------------------------------------------------- pieces

    def _size(self, ctx: TrackContext) -> float:
        return float(self.opt("size") or ctx.theme.label_size)

    def _color(self, ctx: TrackContext) -> Color:
        spec = self.opt("color")
        if spec is None:
            return ctx.theme.effective_label_color()
        try:
            return parse_color(spec)
        except ValueError:
            return ctx.theme.effective_label_color()

    def _row_color(self, ctx: TrackContext, node_id: int, default: Color) -> Color:
        col = self.opt("color_column")
        if col is None:
            return default
        spec = self.data.get(node_id, int(col))
        if spec is None:
            return default
        try:
            return parse_color(spec)
        except ValueError:
            return default

    def _text_of(self, node_id: int) -> str:
        v = self.data.get(node_id, int(self.opt("column", 0)))
        return "" if v is None else str(v)

    def text_width(self, ctx: TrackContext) -> float:
        """Widest label in scene units, measured through the injected metrics."""
        size = self._size(ctx)
        bold = bool(self.opt("bold", False))
        italic = bool(self.opt("italic", False))
        widest = 0.0
        for node_id in self.data.rows:
            text = self._text_of(node_id)
            if not text:
                continue
            w = ctx.metrics.advance(text, size, bold=bold, italic=italic,
                                    family=ctx.theme.font_family)
            if w > widest:
                widest = w
        cap = self.opt("max_width")
        if cap is not None:
            widest = min(widest, float(cap))
        return widest

    # ------------------------------------------------------------ protocol

    def measure(self, ctx: TrackContext) -> float:
        return float(self.opt("margin", 4.0)) + self.text_width(ctx)

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        size = self._size(ctx)
        bold = bool(self.opt("bold", False))
        italic = bool(self.opt("italic", False))
        base_color = self._color(ctx)
        align = _ANCHORS.get(str(self.opt("align", "start")), Anchor.START)
        width = self.text_width(ctx)
        margin = float(self.opt("margin", 4.0))
        rotate = bool(self.opt("rotate_with_layout", True))
        extra = float(self.opt("rotation", 0.0))
        cap = self.opt("max_width")
        opacity = float(self.opt("opacity", 1.0))

        # The anchor decides where in the column the text is pinned, so that a
        # right-aligned column stays flush against the next track outward.
        if align is Anchor.END:
            offset = ctx.offset + margin + width
        elif align is Anchor.MIDDLE:
            offset = ctx.offset + margin + width * 0.5
        else:
            offset = ctx.offset + margin

        for node_id in ctx.tip_ids():
            text = self._text_of(node_id)
            if not text:
                continue
            if cap is not None and self.opt("ellipsize", True):
                text = ctx.metrics.ellipsize(text, size, float(cap), bold=bold,
                                             italic=italic,
                                             family=ctx.theme.font_family)
                if not text:
                    continue
            lo, hi = ctx.rows_of(node_id)
            place = ctx.projector.text((lo + hi) * 0.5, offset, align, rotate)
            style = TextStyle(family=ctx.theme.font_family, size=size,
                              weight=700 if bold else 400, italic=italic,
                              color=self._row_color(ctx, node_id, base_color),
                              anchor=place.anchor, baseline=Baseline.MIDDLE,
                              letter_spacing=float(self.opt("letter_spacing", 0.0)),
                              opacity=opacity)
            sink.add(TextMark(x=place.x, y=place.y, text=text, style=style,
                              rotation=place.rotation + extra,
                              max_width=float(cap) if cap is not None else None,
                              tag=node_id))

    def legend(self) -> Legend:
        """None: a text column names itself, and a swatch of prose is noise."""
        return Legend(title=self.title, items=[], kind="categorical")

# SPDX-License-Identifier: MIT
"""Curved links between arbitrary node pairs.

A connection is not annotation *of* a node, it is annotation of a relation:
gene transfer, recombination, host jumps, co-occurrence.  Two consequences run
through this module.

First, the track consumes **no band thickness at all** -- :meth:`measure`
returns zero.  The links are drawn over the tree body, not in the stack beyond
the tips, so making room for them would push every other track outward for
nothing.  They paint into :data:`~makeyourtree.scene.marks.Layer.CONNECTIONS`,
which sits above the background wash and below the branches, so a dense bundle
of chords never obscures the topology it is drawn against.

Second, :meth:`bind` has to be overridden.  The base implementation resolves
one key per row and stores the row under a node id; a link has two endpoints
and belongs to neither of them, so here each row is stored under a link index
with the two resolved node ids as its first two values.

Routing
-------
This is the one track that legitimately looks at the layout mode, because the
shape that keeps links legible is different in the two geometries and no
band-space formulation covers both:

*polar*
    A quadratic Bezier whose control point is pulled toward the centre of the
    circle.  This is the hierarchical-edge-bundling shape (D. Holten,
    "Hierarchical Edge Bundles", *IEEE TVCG* 12(5), 2006): near neighbours get
    short shallow chords, distant pairs sweep deep through the empty middle,
    and nothing cuts across the ring of tip labels.
*linear*
    The same Bezier bowed the other way -- outward, past the tips -- because
    the middle of a rectangular layout is full of branches and the space beyond
    the tips is not.

``bow`` runs from 0 -- a straight chord -- to 1, where the control point sits
at the circle centre in a polar layout, or clear of the outermost endpoint plus
half the link's own length in a linear one.  Around 0.85 reads best.

Link widths are normalised so the widest link in the dataset lands on
``max_width``; links are drawn thin-first so the heavy ones end up on top.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from ..core.diagnostics import DiagnosticSink
from ..core.tree import Tree
from ..scene.marks import (Anchor, Baseline, Layer, MarkSink, Paint, Path,
                           PathMark, TextMark, TextStyle)
from ..style.color import Color
from .bars import numeric, option_color, safe_color
from .base import (Legend, LegendItem, Track, TrackContext, TrackData,
                   register)

__all__ = ["ConnectionsTrack", "LINK_COLUMNS"]

LINK_COLUMNS: tuple[str, ...] = ("from", "to", "width", "color", "opacity", "label")
"""Column meanings of a bound link row.  ``from``/``to`` hold node ids."""


@register
class ConnectionsTrack(Track):
    """Bezier links between node pairs, painted under the branches."""

    type_id = "connections"
    display_name = "Connections"
    default_layer = Layer.CONNECTIONS
    multi_column = True

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        opts = super().default_options()
        opts.update({
            "opacity": 0.55,
            "bow": 0.85,
            "anchor": "node",
            "band_offset": 0.0,
            "color": None,
            "max_width": 6.0,
            "min_width": 0.6,
            "width_scale": "linear",
            "loop_size": 40.0,
            "show_labels": False,
            "label_size": None,
        })
        return opts

    # ------------------------------------------------------------ binding

    def bind(self, tree: Tree, keys_to_values: dict[str, Sequence[Any]], *,
             columns: Sequence[str] | None = None, match_internal: bool = True,
             sink: DiagnosticSink | None = None) -> None:
        """Resolve *pairs* of node keys into link rows.

        The base class binds one key per row, which cannot express a link.  So
        each entry here is one connection: the mapping key is the link's own
        identifier -- any unique string, a line number does fine -- and the
        value sequence is ``(from_key, to_key, width, colour, opacity, label)``
        with everything after the second field optional.  Rows land under a
        link index rather than a node id, since a link belongs to no single
        node, and the two endpoints are stored as resolved ids so nothing
        downstream has to re-match text.

        An endpoint may be given as a node name or as an integer node id.  A
        link with an unresolvable endpoint is dropped and both offending keys
        are reported through ``data.unmatched``, because half a link is worse
        than none: it would point somewhere the data never meant.
        """
        by_name: dict[str, list[int]] = {}
        for node in tree.nodes:
            if not node.name:
                continue
            if not match_internal and node.children:
                continue
            by_name.setdefault(node.name, []).append(node.id)

        rows: dict[int, list[Any]] = {}
        unmatched: list[str] = []
        index = 0
        for key, values in keys_to_values.items():
            values = list(values)
            if len(values) < 2:
                unmatched.append(str(key))
                continue
            a = _resolve(tree, values[0], by_name)
            b = _resolve(tree, values[1], by_name)
            if a is None or b is None:
                unmatched.extend(str(values[i]) for i, resolved in
                                 ((0, a), (1, b)) if resolved is None)
                continue
            extras = list(values[2:6]) + [None] * max(0, 4 - len(values[2:6]))
            rows[index] = [a, b, *extras]
            index += 1

        self.data = TrackData(
            columns=list(columns) if columns is not None else list(LINK_COLUMNS),
            rows=rows, unmatched=unmatched, source=self.data.source)
        if unmatched and sink is not None:
            shown = ", ".join(unmatched[:5])
            more = f" (+{len(unmatched) - 5} more)" if len(unmatched) > 5 else ""
            sink.warn("track.unmatched",
                      f"{self.display_name} '{self.title}': {len(unmatched)} "
                      f"endpoint key(s) matched no node: {shown}{more}")

    # -------------------------------------------------------------- shape

    def measure(self, ctx: TrackContext) -> float:
        """Zero: links are drawn over the tree, not stacked beyond the tips."""
        return 0.0

    def links(self) -> list[list[Any]]:
        """Bound link rows, ordered thin-first so heavy links paint on top."""
        rows = [list(r) for r in self.data.rows.values() if len(r) >= 2]
        rows.sort(key=lambda r: (numeric(r[2]) if len(r) > 2 else None) or 0.0)
        return rows

    def _width_of(self, raw: Any, widest: float) -> float:
        """Link width, normalised so the dataset's widest lands on ``max_width``."""
        top = max(0.1, float(self.opt("max_width", 6.0) or 6.0))
        floor = max(0.05, float(self.opt("min_width", 0.6) or 0.6))
        v = numeric(raw)
        if v is None or widest <= 0 or v <= 0:
            return max(floor, min(top, top * 0.5))
        share = min(1.0, v / widest)
        if str(self.opt("width_scale", "linear")).lower() == "sqrt":
            share = math.sqrt(share)
        return max(floor, top * share)

    # --------------------------------------------------------------- draw

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        rows = self.links()
        if not rows:
            return
        widths = [v for v in (numeric(r[2]) if len(r) > 2 else None for r in rows)
                  if v is not None]
        widest = max(widths) if widths else 0.0
        default_color = option_color(self, "color", ctx.theme.accent)
        base_opacity = float(self.opt("opacity", 0.55) or 0.55)
        bow = min(max(float(self.opt("bow", 0.85) or 0.0), 0.0), 1.0)
        labels: list[TextMark] = []

        for row in rows:
            a, b = int(row[0]), int(row[1])
            if not (ctx.frame.has(a) and ctx.frame.has(b)):
                continue
            p1 = self._endpoint(ctx, a)
            p2 = self._endpoint(ctx, b)
            color = safe_color(row[3], default_color) if len(row) > 3 and \
                row[3] is not None else default_color
            alpha = numeric(row[4]) if len(row) > 4 else None
            paint = Paint(stroke=color, width=self._width_of(
                row[2] if len(row) > 2 else None, widest),
                opacity=base_opacity if alpha is None else max(0.0, min(1.0, alpha)))
            if a == b or (p1 == p2):
                size = float(self.opt("loop_size", 40.0) or 40.0)
                out = ctx.projector.outward(ctx.frame.row(a))
                sink.add(PathMark(paint=paint, segments=_loop(p1, out, size)))
                control = (p1[0] + out[0] * size, p1[1] + out[1] * size)
            else:
                control = self._control(ctx, a, b, p1, p2, bow)
                sink.add(PathMark(paint=paint, segments=_curve(p1, p2, control)))
            label = row[5] if len(row) > 5 else None
            if label and self.opt("show_labels", False):
                labels.append(self._label(ctx, str(label), p1, p2, control, color))
        for mark in labels:
            sink.add(mark)

    def _endpoint(self, ctx: TrackContext, node_id: int) -> tuple[float, float]:
        """Where a link attaches.

        ``anchor = "node"`` uses the node's own layout position, the only
        placement that works for internal nodes; ``anchor = "band"`` moves the
        attachment out to the track baseline so links clear the tip labels.
        """
        if str(self.opt("anchor", "node")).lower() == "band":
            return ctx.projector.point(ctx.frame.row(node_id),
                                       float(self.opt("band_offset", 0.0) or 0.0))
        return ctx.frame.xy(node_id)

    def _control(self, ctx: TrackContext, a: int, b: int,
                 p1: tuple[float, float], p2: tuple[float, float],
                 bow: float) -> tuple[float, float]:
        mid = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
        if ctx.projector.is_polar:
            centre = _polar_centre(ctx)
            return (mid[0] + bow * (centre[0] - mid[0]),
                    mid[1] + bow * (centre[1] - mid[1]))
        # Bowing by a fraction of the chord length alone is not enough: with
        # one endpoint deep in the tree the curve would still cross it.  So the
        # depth first clears the outermost endpoint, measured along the outward
        # ray, and only then adds the bow proper.
        row = (ctx.frame.row(a) + ctx.frame.row(b)) * 0.5
        ox, oy = ctx.projector.point(row, 0.0)
        ux, uy = ctx.projector.outward(row)
        along = [(p[0] - ox) * ux + (p[1] - oy) * uy for p in (p1, p2, mid)]
        clearance = max(along[0], along[1]) - along[2]
        depth = bow * (clearance + 0.5 * math.hypot(p2[0] - p1[0], p2[1] - p1[1]))
        return (mid[0] + ux * depth, mid[1] + uy * depth)

    def _label(self, ctx: TrackContext, text: str, p1: tuple[float, float],
               p2: tuple[float, float], control: tuple[float, float],
               color: Color) -> TextMark:
        """Placed at the curve's own midpoint, which for a quadratic Bezier is
        ``(P1 + 2C + P2) / 4`` -- not the midpoint of the chord."""
        x = 0.25 * p1[0] + 0.5 * control[0] + 0.25 * p2[0]
        y = 0.25 * p1[1] + 0.5 * control[1] + 0.25 * p2[1]
        size = float(self.opt("label_size") or ctx.theme.track_title_size)
        return TextMark(paint=Paint(), x=x, y=y, text=text,
                        style=TextStyle(family=ctx.theme.font_family, size=size,
                                        color=color, anchor=Anchor.MIDDLE,
                                        baseline=Baseline.MIDDLE))

    # ------------------------------------------------------------- legend

    def legend(self) -> Legend:
        """One line swatch per distinct colour-and-label pair, plus a width key.

        Links carry their meaning in colour and thickness, so the legend has to
        show both; without the width samples a reader cannot tell whether a
        thick chord means "strong" or merely "drawn later".
        """
        seen: dict[tuple[str, str], LegendItem] = {}
        widths: list[float] = []
        for row in self.data.rows.values():
            color = safe_color(row[3], Color(37, 99, 235)) if len(row) > 3 and \
                row[3] is not None else Color(37, 99, 235)
            label = str(row[5]) if len(row) > 5 and row[5] else (self.title or "link")
            seen.setdefault((label, color.hex),
                            LegendItem(label=label, color=color, shape="line"))
            w = numeric(row[2]) if len(row) > 2 else None
            if w is not None:
                widths.append(w)
        items = [seen[k] for k in sorted(seen)]
        if widths and max(widths) > min(widths):
            items.append(LegendItem(label="link weight", shape="line",
                                    value_range=(min(widths), max(widths))))
        return Legend(title=self.title, items=items)


# ---------------------------------------------------------------- helpers


def _resolve(tree: Tree, key: Any, by_name: dict[str, list[int]]) -> int | None:
    """A node id from a name or from an id, or ``None`` when nothing matches."""
    if key is None or key == "":
        return None
    if isinstance(key, int) and not isinstance(key, bool):
        return key if tree.by_id(key) is not None else None
    ids = by_name.get(str(key))
    if ids:
        return ids[0]
    text = str(key)
    if text.isdigit() and tree.by_id(int(text)) is not None:
        return int(text)
    return None


def _polar_centre(ctx: TrackContext) -> tuple[float, float]:
    """The circle centre a polar link bows toward.

    Taken from the projector, which owns the polar frame; the layout frame's
    own ``center`` is the fallback for projectors that do not expose one.
    """
    cx = getattr(ctx.projector, "cx", None)
    cy = getattr(ctx.projector, "cy", None)
    if cx is None or cy is None:
        return ctx.frame.center
    return (float(cx), float(cy))


def _curve(p1: tuple[float, float], p2: tuple[float, float],
           control: tuple[float, float]) -> tuple:
    return (Path().move_to(*p1).quad_to(control[0], control[1], *p2).freeze())


def _loop(point: tuple[float, float], out: tuple[float, float],
          size: float) -> tuple:
    """A self-link: out and back, spread sideways so it reads as a loop."""
    tangent = (-out[1], out[0])
    c1 = (point[0] + out[0] * size - tangent[0] * size * 0.5,
          point[1] + out[1] * size - tangent[1] * size * 0.5)
    c2 = (point[0] + out[0] * size + tangent[0] * size * 0.5,
          point[1] + out[1] * size + tangent[1] * size * 0.5)
    return (Path().move_to(*point).cubic_to(*c1, *c2, *point).freeze())

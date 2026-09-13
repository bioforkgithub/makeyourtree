# SPDX-License-Identifier: MIT
"""Heatmap: many numeric columns as a matrix beside the tree.

Scale is the whole problem here.  Two hundred columns over five thousand tips
is a million cells, so the track never emits a mark per cell: every cell is
queued into a :class:`~makeyourtree.tracks.shapes.QuadBatch`, which collapses the
lot into one batched mark in linear layouts and into one path per distinct
ramp colour in polar ones.  Mark count is therefore O(columns) -- the column
labels -- and never O(cells).

Normalisation is explicit rather than implicit.  ``global`` shares one domain
across the whole matrix and is right when every cell carries the same unit;
``column`` gives each column its own domain and is right when the columns have
different units; ``row`` normalises each taxon's profile, which makes rows
comparable to each other and columns not.  Choosing wrongly does not produce an
error, it produces a plausible and misleading picture, so the choice is a
first-class option and the legend says which one is in force.

Clustering is **off by default**.  Reordering the columns of a matrix changes
what the reader infers from adjacency, and doing that silently would be a
misrepresentation of the input; the user asks for it or it does not happen.
Row clustering cannot be applied by a track at all -- tip rows belong to the
layout -- so :meth:`HeatmapTrack.suggest_row_order` computes the order and
hands it back for the caller to apply to the tree.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from ..scene.marks import (Anchor, Baseline, MarkSink, TextMark, TextStyle)
from ..style.color import Color, parse_color
from .base import Legend, LegendItem, Track, TrackContext, register
from .gradient import (DEFAULT_MISSING, DEFAULT_SEQUENTIAL, ColorRamp,
                       ramp_from_options, to_float)
from .shapes import QuadBatch

__all__ = ["HeatmapTrack", "average_linkage_order"]


def average_linkage_order(vectors: Sequence[Sequence[float | None]]) -> list[int]:
    """Leaf order of an average-linkage (UPGMA) dendrogram over *vectors*.

    Sokal & Michener (1958).  Distance is Euclidean over the entries both
    vectors actually have, scaled by the count so that pairs sharing few
    entries are not flattered by a short sum.  Agglomeration is iterative and
    keeps each cluster's member order, so the final cluster *is* the order --
    no tree walk, and nothing to recurse over.
    """
    n = len(vectors)
    if n < 3:
        return list(range(n))

    def dist(a: Sequence[float | None], b: Sequence[float | None]) -> float:
        total = 0.0
        shared = 0
        for x, y in zip(a, b):
            if x is None or y is None:
                continue
            total += (x - y) * (x - y)
            shared += 1
        if shared == 0:
            return math.inf
        return math.sqrt(total / shared)

    d: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            d[(i, j)] = dist(vectors[i], vectors[j])
    members: dict[int, list[int]] = {i: [i] for i in range(n)}
    active = list(range(n))
    next_id = n
    while len(active) > 1:
        best = None
        best_d = math.inf
        for ai in range(len(active)):
            for bi in range(ai + 1, len(active)):
                p, q = active[ai], active[bi]
                key = (p, q) if p < q else (q, p)
                val = d.get(key, math.inf)
                if val < best_d:
                    best_d, best = val, (p, q)
        if best is None:
            # Nothing left is comparable -- every remaining pair shares no
            # observed entry.  Merge in index order rather than stopping, so
            # incomparable columns keep their input order instead of vanishing.
            best = (active[0], active[1])
        p, q = best
        np_, nq = len(members[p]), len(members[q])
        for r in active:
            if r in (p, q):
                continue
            dp = d.get((min(p, r), max(p, r)), math.inf)
            dq = d.get((min(q, r), max(q, r)), math.inf)
            if math.isinf(dp) and math.isinf(dq):
                merged = math.inf
            elif math.isinf(dp):
                merged = dq
            elif math.isinf(dq):
                merged = dp
            else:
                merged = (dp * np_ + dq * nq) / (np_ + nq)
            d[(min(next_id, r), max(next_id, r))] = merged
        members[next_id] = members[p] + members[q]
        active = [x for x in active if x not in (p, q)] + [next_id]
        next_id += 1
    return members[active[0]]


@register
class HeatmapTrack(Track):
    """A numeric matrix, one column per data column, one row per tip."""

    type_id = "heatmap"
    display_name = "Heatmap"
    needs_numeric = True
    multi_column = True

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        o = super().default_options()
        o.update({
            "cell_size": 20.0,
            "cell_gap": 0.0,
            "margin": 0.0,
            "normalize": "global",
            "color_min": DEFAULT_SEQUENTIAL[0],
            "color_mid": DEFAULT_SEQUENTIAL[1],
            "color_max": DEFAULT_SEQUENTIAL[2],
            "use_mid": True,
            "stops": None,
            "ramp_steps": 256,
            "min_value": None,
            "max_value": None,
            "missing": "fill",
            "missing_color": DEFAULT_MISSING,
            "missing_label": "no value",
            "cluster_columns": False,
            "cluster_rows": False,
            "column_labels": True,
            "label_size": None,
            "label_rotation": -90.0,
            "label_color": None,
            "show_values": False,
            "value_format": "{:.3g}",
            "value_size": 8.0,
            "legend_samples": 24,
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

    def column_order(self) -> list[int]:
        """Display order of the columns.  Identity unless clustering is asked for."""
        n = self.column_count()
        if not self.opt("cluster_columns", False) or n < 3:
            return list(range(n))
        tips = list(self.data.rows)
        vectors = [[to_float(self.data.get(nid, c)) for nid in tips] for c in range(n)]
        return average_linkage_order(vectors)

    def suggest_row_order(self) -> list[int]:
        """Node ids in clustered row order, for a caller that can reorder tips.

        The track cannot apply this itself: which tip owns which band-space row
        is decided by the layout, and a track that moved rows would disagree
        with the branches drawn next to it.
        """
        ids = list(self.data.rows)
        if not self.opt("cluster_rows", False) or len(ids) < 3:
            return ids
        n = self.column_count()
        vectors = [[to_float(self.data.get(nid, c)) for c in range(n)] for nid in ids]
        return [ids[i] for i in average_linkage_order(vectors)]

    # --------------------------------------------------------------- scale

    def _ramp(self) -> ColorRamp:
        """A ramp over ``[0, 1]``; normalisation happens before the lookup so
        that per-column and per-row domains share one quantised table."""
        return ramp_from_options(self.options, (0.0, 1.0))

    def display_domain(self) -> tuple[float, float]:
        lo, hi = self.opt("min_value"), self.opt("max_value")
        found = self.data.value_range(None) or (0.0, 1.0)
        return (float(lo) if lo is not None else found[0],
                float(hi) if hi is not None else found[1])

    def _domains(self, columns: Sequence[int]) -> dict[Any, tuple[float, float]]:
        """Normalisation domain per key, keyed by column index, node id or None."""
        mode = str(self.opt("normalize", "global"))
        if mode == "column":
            out: dict[Any, tuple[float, float]] = {}
            for c in columns:
                out[c] = self.data.value_range(c) or (0.0, 1.0)
            return out
        if mode == "row":
            out = {}
            for nid, row in self.data.rows.items():
                vals = [v for v in (to_float(row[c]) for c in columns
                                    if c < len(row)) if v is not None]
                out[nid] = (min(vals), max(vals)) if vals else (0.0, 1.0)
            return out
        return {None: self.display_domain()}

    def _domain_for(self, domains: dict[Any, tuple[float, float]],
                    column: int, node_id: int) -> tuple[float, float]:
        mode = str(self.opt("normalize", "global"))
        if mode == "column":
            return domains.get(column, (0.0, 1.0))
        if mode == "row":
            return domains.get(node_id, (0.0, 1.0))
        return domains[None]

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
        return (float(self.opt("margin", 0.0))
                + self.column_count() * float(self.opt("cell_size", 20.0)))

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        columns = self.column_order()
        if not columns:
            return
        ramp = self._ramp()
        domains = self._domains(columns)
        miss = self._missing_color()
        cell = float(self.opt("cell_size", 20.0))
        gap = max(0.0, float(self.opt("cell_gap", 0.0))) * 0.5
        base = ctx.offset + float(self.opt("margin", 0.0))
        border = self.opt("border_color")
        batch = QuadBatch(
            ctx.projector, opacity=float(self.opt("opacity", 1.0)),
            stroke=parse_color(border) if border else None,
            stroke_width=float(self.opt("border_width", 0.0)))

        values: list[tuple[float, float, float, Color]] = []
        show_values = bool(self.opt("show_values", False))
        for nid in ctx.tip_ids():
            row = self.data.rows.get(nid)
            if row is None:
                continue
            lo, hi = ctx.rows_of(nid)
            for slot, c in enumerate(columns):
                v = to_float(row[c]) if c < len(row) else None
                if v is None:
                    color = miss
                else:
                    dlo, dhi = self._domain_for(domains, c, nid)
                    t = 0.5 if dhi - dlo <= 0 else (v - dlo) / (dhi - dlo)
                    color = ramp.at(t)
                if color is None:
                    continue
                off0 = base + slot * cell + gap
                off1 = base + (slot + 1) * cell - gap
                batch.add(lo, hi, off0, off1, color)
                if show_values and v is not None:
                    values.append(((lo + hi) * 0.5, (off0 + off1) * 0.5, v, color))
        batch.flush(sink)

        if self.opt("column_labels", True):
            self._draw_column_labels(ctx, sink, columns, base, cell)
        for row_mid, off_mid, v, color in values:
            self._draw_value(ctx, sink, row_mid, off_mid, v, color)

    def _draw_column_labels(self, ctx: TrackContext, sink: MarkSink,
                            columns: Sequence[int], base: float, cell: float) -> None:
        """One label per column, at the head of the matrix.

        ``label_rotation`` is measured **from the outward direction**, so it
        means the same thing in every layout: the default of -90 degrees puts
        linear labels upright above their column and polar labels along the arc,
        which is where they have room in each case.
        """
        size = float(self.opt("label_size") or ctx.theme.track_title_size)
        color = self.opt("label_color")
        style_color = parse_color(color) if color else ctx.theme.muted
        rot = float(self.opt("label_rotation", -90.0))
        for slot, c in enumerate(columns):
            name = self.column_name(c)
            if not name:
                continue
            off = base + (slot + 0.5) * cell
            place = ctx.projector.text(-0.3, off, Anchor.START, rotate=True)
            style = TextStyle(family=ctx.theme.font_family, size=size,
                              color=style_color, anchor=place.anchor,
                              baseline=Baseline.MIDDLE)
            sink.add(TextMark(x=place.x, y=place.y, text=name, style=style,
                              rotation=place.rotation + rot))

    def _draw_value(self, ctx: TrackContext, sink: MarkSink, row: float,
                    offset: float, value: float, fill: Color) -> None:
        place = ctx.projector.text(row, offset, Anchor.MIDDLE, rotate=True)
        style = TextStyle(family=ctx.theme.font_family,
                          size=float(self.opt("value_size", 8.0)),
                          color=fill.readable_text(), anchor=Anchor.MIDDLE,
                          baseline=Baseline.MIDDLE)
        text = str(self.opt("value_format", "{:.3g}")).format(value)
        sink.add(TextMark(x=place.x, y=place.y, text=text, style=style,
                          rotation=place.rotation))

    def legend(self) -> Legend:
        ramp = self._ramp()
        mode = str(self.opt("normalize", "global"))
        normalised = mode in ("column", "row")
        rng = (0.0, 1.0) if normalised else self.display_domain()
        label = self.title or "value"
        if normalised:
            label = f"{label} ({mode}-normalised)"
        items = [LegendItem(label=label, shape="gradient", color=ramp.at(1.0),
                            gradient=ramp.sample(int(self.opt("legend_samples", 24))),
                            value_range=rng)]
        miss = self._missing_color()
        if miss is not None:
            items.append(LegendItem(label=str(self.opt("missing_label", "no value")),
                                    color=miss, shape="square"))
        return Legend(title=self.title, items=items, kind="continuous")

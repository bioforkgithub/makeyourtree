# SPDX-License-Identifier: MIT
"""Colour strip: one band per tip, driven by a categorical scale.

The simplest possible track, and the one that carries the categorical colour
machinery every other categorical track reuses (:class:`CategoryColors`).

Two rendering details are worth stating.  Adjacent tips sharing a colour are
merged into a single quad before emission: on a taxonomy strip that collapses
thousands of cells into tens, and it removes the hairline seams that
anti-aliasing leaves between abutting rectangles.  And a tip with no value
leaves a genuine gap -- it breaks the run and nothing is drawn -- because a
default colour would assert membership of a category the data never claimed.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from ..core.traversal import postorder
from ..scene.compose import compositor_owns_titles
from ..scene.marks import Anchor, Baseline, MarkSink, TextMark, TextStyle
from ..style.color import Color, parse_color
from .base import Legend, LegendItem, Track, TrackContext, TrackData, register
from .shapes import QuadBatch

__all__ = ["ColorStripTrack", "CategoryColors", "palette_colors",
           "FALLBACK_CATEGORICAL"]

FALLBACK_CATEGORICAL: tuple[Color, ...] = tuple(parse_color(h) for h in (
    "#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7",
    "#56B4E9", "#F0E442", "#7F5A83", "#3E5C41", "#8C4A2F",
))
"""Colour-vision-deficiency-safe defaults (Okabe & Ito's recommended set plus
four extensions of our own), used when :mod:`makeyourtree.style.palettes` cannot
supply the requested palette."""

_COLOR_PREFIXES = ("#", "rgb(", "rgba(", "hsl(", "hsla(")


def palette_colors(name: str | None) -> tuple[Color, ...]:
    """Palette *name* from :mod:`makeyourtree.style.palettes`, or the fallback.

    An unknown NAME falls back to the built-in cycle: palettes come from
    user-supplied tables, and a mistyped one is a cosmetic problem, not a
    reason to fail a whole figure.  The registry itself is imported plainly --
    the guard that used to wrap it dated from when ``style/palettes.py`` was
    still being written, and would now hide a real breakage.
    """
    if not name:
        return FALLBACK_CATEGORICAL
    from ..style.palettes import get_palette

    try:
        pal: Any = get_palette(name)
    except (KeyError, ValueError, TypeError):
        return FALLBACK_CATEGORICAL
    pal = getattr(pal, "colors", pal)
    try:
        out = tuple(parse_color(c) for c in pal)
    except (TypeError, ValueError):
        return FALLBACK_CATEGORICAL
    return out or FALLBACK_CATEGORICAL


def looks_like_color(value: Any) -> bool:
    """True for hex and functional colour notation only.

    Deliberately excludes named colours: ``red`` is far more often a category
    in a real table than a request for pure red, and a category keeps its
    palette colour and its legend entry.
    """
    if isinstance(value, Color):
        return True
    if not isinstance(value, str):
        return False
    s = value.strip().lower()
    return s.startswith(_COLOR_PREFIXES)


class CategoryColors:
    """Categorical value -> colour.

    Explicit assignments win; every other category is dealt from the palette in
    **first-seen order**, cycling if the palette runs out.  First-seen rather
    than sorted, because a table that lists its categories in a meaningful
    sequence (severity, taxonomic rank) should keep it in the legend too.

    Values that are literally colours pass through unchanged, which is how a
    strip built from baked ``#rrggbb`` cells works without any category at all.
    """

    __slots__ = ("_map", "_order", "_palette", "_next", "_literal")

    def __init__(self, categories: Iterable[Any] = (), *,
                 explicit: dict[str, Any] | None = None,
                 palette: Sequence[Color] | None = None,
                 literal_colors: bool = True) -> None:
        self._palette = tuple(palette) if palette else FALLBACK_CATEGORICAL
        self._literal = literal_colors
        self._map: dict[str, Color] = {}
        self._order: list[str] = []
        self._next = 0
        for k, v in (explicit or {}).items():
            try:
                self._map[str(k)] = parse_color(v)
            except ValueError:
                continue
        for c in categories:
            self.color(c)

    def color(self, value: Any) -> Color | None:
        """Colour for *value*, assigning one on first sight.  None when absent."""
        if value is None or value == "":
            return None
        if self._literal and looks_like_color(value):
            try:
                return parse_color(value)
            except ValueError:
                return None
        key = str(value)
        hit = self._map.get(key)
        if hit is None:
            hit = self._palette[self._next % len(self._palette)]
            self._next += 1
            self._map[key] = hit
        if key not in self._order:
            self._order.append(key)
        return hit

    def __call__(self, value: Any) -> Color | None:
        return self.color(value)

    def items(self) -> list[tuple[str, Color]]:
        """Assigned categories in first-seen order."""
        return [(k, self._map[k]) for k in self._order if k in self._map]


@register
class ColorStripTrack(Track):
    """One coloured band per tip."""

    type_id = "color-strip"
    display_name = "Colour strip"

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        o = super().default_options()
        o.update({
            "thickness": 22.0,
            "margin": 0.0,
            "palette": None,
            "colors": {},
            "literal_colors": True,
            "merge_runs": True,
            "color_labels": False,
            "color_branches": False,
            "missing": "skip",
            "missing_color": None,
            "title_size": None,
            "title_rotation": 0.0,
            "label_column": 1,
        })
        return o

    # ------------------------------------------------------------- colours

    def _scale(self, ctx: TrackContext | None = None) -> CategoryColors:
        """Build the category scale.  Never cached on the instance: ``measure``
        must not mutate the track, and rebuilding is O(tips)."""
        theme_palette = ctx.theme.categorical_palette if ctx is not None else None
        return CategoryColors(
            self.data.categories(0),
            explicit=self.opt("colors") or {},
            palette=palette_colors(self.opt("palette") or theme_palette),
            literal_colors=bool(self.opt("literal_colors", True)),
        )

    def _missing_color(self) -> Color | None:
        if self.opt("missing") != "fill":
            return None
        spec = self.opt("missing_color")
        if spec is None:
            return None
        try:
            return parse_color(spec)
        except ValueError:
            return None

    def tip_colors(self, ctx: TrackContext) -> dict[int, Color]:
        """Colour per tip node id.  Tips with no value are simply absent."""
        scale = self._scale(ctx)
        miss = self._missing_color()
        out: dict[int, Color] = {}
        for nid in ctx.tip_ids():
            c = scale.color(self.data.get(nid, 0))
            if c is None:
                c = miss
            if c is not None:
                out[nid] = c
        return out

    def label_colors(self, ctx: TrackContext) -> dict[int, Color]:
        """Tip-label colours the compositor should apply, or nothing.

        The strip cannot recolour a tip label itself -- labels belong to the
        tree body, which the compositor draws -- so the option is answered here
        and applied there.
        """
        if not self.opt("color_labels", False):
            return {}
        return self.tip_colors(ctx)

    def branch_colors(self, ctx: TrackContext) -> dict[int, Color]:
        """Colour per node for branch tinting, propagated bottom-up.

        A node takes a colour only when every visible descendant tip agrees, so
        a mixed clade stays neutral instead of inheriting an arbitrary child's
        colour.  Iterative postorder: a caterpillar tree would blow the stack.
        Empty unless ``color_branches`` is set, for the same reason as
        :meth:`label_colors`: the branches are not ours to draw.
        """
        if not self.opt("color_branches", False):
            return {}
        tips = self.tip_colors(ctx)
        out: dict[int, Color] = {}
        for node in postorder(ctx.tree.root, visible_only=True):
            if node.id in tips:
                out[node.id] = tips[node.id]
                continue
            kids = node.children
            if not kids:
                continue
            first = out.get(kids[0].id)
            if first is not None and all(out.get(k.id) == first for k in kids[1:]):
                out[node.id] = first
        return out

    # ------------------------------------------------------------ protocol

    def measure(self, ctx: TrackContext) -> float:
        return float(self.opt("margin", 0.0)) + float(self.opt("thickness", 22.0))

    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        colors = self.tip_colors(ctx)
        off0 = ctx.offset + float(self.opt("margin", 0.0))
        off1 = off0 + float(self.opt("thickness", 22.0))
        border = self.opt("border_color")
        batch = QuadBatch(
            ctx.projector, opacity=float(self.opt("opacity", 1.0)),
            stroke=parse_color(border) if border else None,
            stroke_width=float(self.opt("border_width", 0.0)))

        merge = bool(self.opt("merge_runs", True))
        run_lo = run_hi = 0.0
        run_color: Color | None = None
        for nid in ctx.tip_ids():
            c = colors.get(nid)
            lo, hi = ctx.rows_of(nid)
            if c is not None and run_color == c and merge and lo <= run_hi + 1e-9:
                run_hi = hi
                continue
            if run_color is not None:
                batch.add(run_lo, run_hi, off0, off1, run_color)
            run_color, run_lo, run_hi = c, lo, hi
        if run_color is not None:
            batch.add(run_lo, run_hi, off0, off1, run_color)
        batch.flush(sink)

        # No data, no title: a caption floating beside an empty column says
        # nothing and only crowds the next track.
        if colors and self.opt("show_title", True) and self.title \
                and not compositor_owns_titles(ctx):
            self._draw_title(ctx, sink, (off0 + off1) * 0.5)

    def _draw_title(self, ctx: TrackContext, sink: MarkSink, off_mid: float) -> None:
        """Title at the strip's head: one row before the first tip.

        Reached only when this track is drawn OUTSIDE the compositor, which is
        the one case in which a self-drawn caption cannot collide with anything
        -- there is no stack for it to collide with.  Inside :func:`compose`
        the whole header row is solved at once, because a title wider than its
        own column has to be turned or staggered and only the compositor knows
        what the neighbours are.  See
        :func:`makeyourtree.scene.compose.draw_track_title`.
        """
        size = float(self.opt("title_size") or ctx.theme.track_title_size)
        place = ctx.projector.text(-0.7, off_mid, Anchor.MIDDLE, rotate=True)
        style = TextStyle(family=ctx.theme.font_family, size=size,
                          color=ctx.theme.muted, anchor=place.anchor,
                          baseline=Baseline.MIDDLE)
        sink.add(TextMark(x=place.x, y=place.y, text=self.title, style=style,
                          rotation=place.rotation + float(self.opt("title_rotation", 0.0))))

    def legend(self) -> Legend:
        scale = CategoryColors(
            self.data.categories(0), explicit=self.opt("colors") or {},
            palette=palette_colors(self.opt("palette")),
            literal_colors=bool(self.opt("literal_colors", True)))
        label_col = int(self.opt("label_column", 1))
        labels = self._labels_by_value(label_col)
        seen: set[tuple[str, str]] = set()
        items: list[LegendItem] = []
        for value, color in _distinct_values(self.data, scale):
            label = labels.get(value, value)
            key = (label, color.hex)
            if key in seen:
                continue
            seen.add(key)
            items.append(LegendItem(label=label, color=color, shape="square"))
        return Legend(title=self.title, items=items, kind="categorical")

    def _labels_by_value(self, column: int) -> dict[str, str]:
        if column <= 0 or column >= len(self.data.columns):
            return {}
        out: dict[str, str] = {}
        for row in self.data.rows.values():
            if column >= len(row) or row[0] in (None, ""):
                continue
            lab = row[column]
            if lab not in (None, ""):
                out.setdefault(str(row[0]), str(lab))
        return out


def _distinct_values(data: TrackData, scale: CategoryColors
                     ) -> list[tuple[str, Color]]:
    """Distinct column-0 values with their colours, in first-seen order."""
    out: list[tuple[str, Color]] = []
    seen: set[str] = set()
    for row in data.rows.values():
        if not row or row[0] in (None, ""):
            continue
        key = str(row[0])
        if key in seen:
            continue
        seen.add(key)
        c = scale.color(row[0])
        if c is not None:
            out.append((key, c))
    return out

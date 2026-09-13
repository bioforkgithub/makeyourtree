# SPDX-License-Identifier: MIT
"""The compositor: a :class:`~makeyourtree.doc.document.Document` becomes a Scene.

This is the only place that knows both about trees and about marks.  Layouts
produce coordinates, tracks produce band-space drawings, themes produce colour;
:func:`compose` is what turns all of it into one flat, backend-agnostic display
list.  Everything downstream -- the SVG writer, the Qt canvas, the raster
exporter -- consumes that display list and nothing else, which is what keeps the
screen and the export in agreement.

Two decisions dominate the implementation.

**Batching.**  A 100 000-leaf tree has ~200 000 branch segments but a handful of
distinct pens.  Branches are therefore bucketed by *resolved paint* and emitted
as one :class:`~makeyourtree.scene.marks.LinesMark` per bucket (one
:class:`~makeyourtree.scene.marks.PathMark` per bucket for polar arc connectors), so
mark count is O(distinct paints), not O(nodes).  Style resolution is done with a
single preorder walk that carries inherited values down the stack rather than
calling :func:`makeyourtree.style.theme.resolve` per node, which would be O(n x
depth) and quadratic on a caterpillar tree.

**Two-phase track stacking.**  Every visible track is measured first, band
offsets are accumulated, and only then is ``draw`` called with a final offset
(see :mod:`makeyourtree.tracks.base`).  A track that tried to grow the stack while
drawing would corrupt the tracks after it, so the offsets are frozen before any
drawing begins.

Scale-bar and axis tick values use the "nice number" rounding of P. S. Heckbert,
*Nice Numbers for Graph Labels*, Graphics Gems I (Academic Press, 1990), which
picks a step from {1, 2, 5} x 10^k so that labels read as round numbers.
"""

from __future__ import annotations

import dataclasses
import math
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from ..core.diagnostics import DiagnosticSink
from ..core.node import Node
from ..layout.params import LayoutMode, LayoutParams
from ..style.color import Color, parse_color
from ..style.theme import INHERITED_KEYS, Theme
from ..text.metrics import TextMetrics, default_metrics
from .legend import build_legend
from .marks import (Anchor, Baseline, Cap, EllipseMark, GroupMark, ImageMark,
                    Join, Layer, LinesMark, Mark, MarkSink, Paint, Path,
                    PathMark, PolygonMark, PolylineMark, RectMark, RectsMark,
                    Scene, TextMark, TextStyle)

if TYPE_CHECKING:  # pragma: no cover - typing only
    # makeyourtree.layout.projector imports makeyourtree.scene, which imports this
    # module, so the frame and projector types are annotation-only here to keep
    # the package import graph acyclic.
    from ..doc.document import Document
    from ..layout.frame import Bounds, LayoutFrame
    from ..layout.projector import Projector
    from ..tracks.base import Track, TrackContext

__all__ = ["compose", "draw_track_title", "compositor_owns_titles",
           "TRACK_TITLE_OWNER_KEY"]

_EPS = 1e-9
_ANGLE_EPS = 1e-7

TRACK_TITLE_OWNER_KEY = "track_title_owner"
"""``frame.metadata`` flag saying that the compositor has claimed the header row.

Only the compositor knows the whole track stack, so only the compositor can lay
a header row out without collisions -- see :func:`_plan_track_titles`.  A track
drawn on its own, outside :func:`compose`, has no stack and cannot collide with
anything, so it still captions itself; this key is how it tells the two
situations apart.
"""

HEADER_GAP_ROWS = 0.35
"""Rows between the first tip and the nearest edge of the header row."""

HEADER_PAD_ROWS = 0.25
"""Rows of clearance between two header rows."""

HEADER_GAP_SHARE = 0.25
"""Most of a fan's header budget the clearance before the first caption may take.

Beside a rectangular tree the clearance can be a fixed number of rows, because
the page grows to hold whatever the header needs.  A fan has no such freedom:
its header lives in the wedge the arc leaves open, and a fixed 0.35 rows is most
of the gap a 350 degree fan of sixteen tips has to offer.  Scaling the clearance
to the room available keeps it a margin rather than the whole budget.
"""

HEADER_PAD = 4.0
"""Clearance along the band offset axis between two titles, in scene units."""

MAX_HEADER_DEPTH = 140.0
"""How far a turned title may reach away from the tree before it is cut.

A caption longer than this is a sentence, not a label: letting it run would
push the page out further than the figure it annotates.
"""


def compose(document: "Document", *, size: tuple[float, float] | None = None,
            interactive: bool = False,
            sink: DiagnosticSink | None = None) -> Scene:
    """Lay *document* out and build its :class:`Scene`.

    *size* requests a page size in scene units.  It is a floor, never a clip:
    if the figure needs more room the page grows, because silently cropping a
    tree is worse than handing back a page larger than asked for.

    *interactive* is forwarded to tracks so they may add hover affordances that
    an export must not contain.  It does not by itself add overlay marks --
    selection and hover are owned by the canvas, which paints
    ``Layer.OVERLAY`` on top of this scene.

    Text is measured through ``document.metadata["text_metrics"]`` when the
    application has injected a real font engine, and through the Qt-free
    fallback otherwise.
    """
    from ..layout import compute_layout

    theme = document.theme
    params = document.params
    metrics = _metrics_for(document)
    frame = compute_layout(document.tree, params, metrics)
    _report_clamped_lengths(frame, sink)

    scene = Scene(background=theme.background)
    scene.metadata["frame"] = frame

    stack = _stack_tracks(document, frame, theme, metrics, interactive, sink)
    scene.metadata["track_offsets"] = {t.id: off for t, off, _ in stack}
    # Claimed before the first ``draw`` so no track captions itself as well.
    frame.metadata[TRACK_TITLE_OWNER_KEY] = "compose"

    _emit_clade_fills(scene, document, frame, theme, stack)
    _emit_branches(scene, document, frame, params, theme)
    _emit_collapsed(scene, document, frame, params, theme)
    _draw_tracks(scene, document, frame, theme, metrics, stack, interactive, sink)
    _emit_track_titles(scene, frame, theme, metrics, stack, sink)
    _emit_guides(scene, frame, params, theme)
    _emit_labels(scene, document, frame, params, theme, metrics)
    _emit_support(scene, document, frame, theme)
    _emit_node_markers(scene, document, frame, theme)
    _emit_axis(scene, frame, params, theme)
    _emit_scalebar(scene, frame, params, theme, metrics)

    bounds = _scene_bounds(scene, metrics)
    legend_marks, lw, lh = build_legend(document.visible_tracks(), theme,
                                        bounds, metrics=metrics)
    for mark in legend_marks:
        scene.add(mark, Layer.LEGEND)
    if legend_marks:
        bounds = _union(bounds, _scene_bounds(scene, metrics))
    scene.metadata["content_bounds"] = bounds
    scene.metadata["legend_size"] = (lw, lh)

    _finalise(scene, bounds, params.margin, size)
    return scene


# --------------------------------------------------------------- plumbing


def _report_clamped_lengths(frame: "LayoutFrame",
                            sink: DiagnosticSink | None) -> None:
    """Pass on the count the layout published under ``negative_lengths_clamped``.

    The layout is the only place that knows how many edges it flattened, and it
    has no sink; the compositor has a sink and no way to recount without
    repeating the traversal.  The frame carries the number between them.
    """
    if sink is None:
        return
    from ..layout.along import NEGATIVE_METADATA_KEY

    clamped = int(frame.metadata.get(NEGATIVE_METADATA_KEY, 0) or 0)
    if clamped:
        sink.warn("layout.negative-lengths-clamped",
                  f"{clamped} negative branch length(s) were drawn as "
                  f"zero-length edges; the data are unchanged")


def _metrics_for(document: "Document") -> TextMetrics:
    injected = document.metadata.get("text_metrics")
    return injected if injected is not None else default_metrics()


def _base_along(proj: Projector | None) -> float:
    """Scene-space origin of the band ``offset`` axis."""
    if proj is None:
        return 0.0
    return float(getattr(proj, "base_r", 0.0) if proj.is_polar
                 else getattr(proj, "base_x", 0.0))


def _along(frame: LayoutFrame, proj: Projector | None, node_id: int) -> float:
    """Node position on the band ``offset`` axis, in scene units."""
    if proj is not None and proj.is_polar:
        return frame.radius(node_id)
    return frame.x(node_id)


def _offset_of(frame: LayoutFrame, proj: Projector | None, node_id: int) -> float:
    return _along(frame, proj, node_id) - _base_along(proj)


def _as_color(value: Any, fallback: Color) -> Color:
    if isinstance(value, Color):
        return value
    if value is None:
        return fallback
    try:
        return parse_color(value)
    except ValueError:
        return fallback


def _as_dash(value: Any) -> tuple[float, ...] | None:
    if not value:
        return None
    return tuple(float(v) for v in value)


def _visible_nodes(document: "Document") -> Iterable[Node]:
    """Preorder over the visible tree.  Iterative -- see :mod:`makeyourtree.core.traversal`."""
    from ..core.traversal import preorder
    return preorder(document.tree.root, visible_only=True)


# ------------------------------------------------------------ track stacking


def _stack_tracks(document: "Document", frame: LayoutFrame, theme: Theme,
                  metrics: TextMetrics, interactive: bool,
                  sink: DiagnosticSink | None) -> list[tuple["Track", float, float]]:
    """Measure every visible track and freeze its band offset.

    Returns ``(track, offset, thickness)`` triples.  Nothing is drawn here: the
    contract in :mod:`makeyourtree.tracks.base` says ``measure`` is pure and the
    whole stack is known before the first ``draw``, and the only way to honour
    that is to complete the measuring pass first.
    """
    tracks = document.visible_tracks()
    if not tracks or frame.projector is None:
        if tracks and frame.projector is None and sink is not None:
            sink.warn("compose.no-projector",
                      f"{document.params.mode.value} layout exposes no band "
                      f"projector; {len(tracks)} track(s) were not drawn")
        return []
    if tracks and sink is not None and frame.metadata.get("band_space") == "approximate":
        # An unrooted layout supplies a band space so tracks still draw, but it
        # is a plain column beside the bounding box: rows are in tree order and
        # no row lines up with the branch it labels.  The frame says so; the
        # user cannot see that it did unless someone passes it on.
        sink.warn("compose.approximate-band-space",
                  f"{document.params.mode.value} layout has no tip order, so "
                  f"the {len(tracks)} attached track(s) are positioned "
                  f"indicatively rather than against their branches: "
                  + str(frame.metadata.get("band_space_note", "")))
    from ..tracks.base import TrackContext

    out: list[tuple[Track, float, float]] = []
    offset = frame.tip_offset + theme.track_margin
    for index, track in enumerate(tracks):
        gap_before = track.opt("gap_before")
        if index > 0:
            offset += float(gap_before) if gap_before is not None else theme.track_gap
        elif gap_before is not None:
            offset += float(gap_before)
        ctx = TrackContext(tree=document.tree, frame=frame,
                           projector=frame.projector, theme=theme,
                           metrics=metrics, offset=offset, index=index,
                           interactive=interactive, sink=sink)
        thickness = max(0.0, float(track.measure(ctx)))
        out.append((track, offset, thickness))
        offset += thickness
    return out


def _draw_tracks(scene: Scene, document: "Document", frame: LayoutFrame,
                 theme: Theme, metrics: TextMetrics,
                 stack: Sequence[tuple["Track", float, float]],
                 interactive: bool, sink: DiagnosticSink | None) -> None:
    if not stack:
        return
    from ..tracks.base import TrackContext

    for index, (track, offset, _thickness) in enumerate(stack):
        ctx = TrackContext(tree=document.tree, frame=frame,
                           projector=frame.projector, theme=theme,
                           metrics=metrics, offset=offset, index=index,
                           interactive=interactive, sink=sink)
        track.draw(ctx, MarkSink(scene, track.default_layer))


# ------------------------------------------------------------ track titles


@dataclasses.dataclass(slots=True)
class _TitleBox:
    """One track caption and the band-space room it needs.

    Kept in band space -- ``offset`` along the stack, ``depth`` in rows away
    from the first tip -- because that is the space in which "does this title
    sit on top of that one" is a plain rectangle test in both layout families.
    The same test in scene space would have to reason about annular sectors.
    """

    track_id: str
    text: str
    size: float
    offset: float
    """Band offset of the title's centre: the middle of its own track."""
    span: float
    """Extent along the offset axis, centred on :attr:`offset`."""
    rows: float
    """Extent along the row axis."""
    across: bool
    """True when the glyph run crosses the band instead of following it."""
    depth: float = 0.0
    """Rows between the first tip and the near edge of this title."""

    @property
    def near(self) -> float:
        return self.offset - 0.5 * self.span - 0.5 * HEADER_PAD

    @property
    def far(self) -> float:
        return self.offset + 0.5 * self.span + 0.5 * HEADER_PAD


def compositor_owns_titles(ctx: "TrackContext") -> bool:
    """True when :func:`compose` has claimed the header row for *ctx*'s frame.

    A track asks this before captioning itself.  It is not a feature flag: it
    is the difference between a track drawn inside a stack, where the caption
    has to be placed against its neighbours, and a track drawn on its own,
    where it cannot collide with anything.
    """
    return bool(ctx.frame.metadata.get(TRACK_TITLE_OWNER_KEY))


def draw_track_title(title: str, *, projector: "Projector", theme: Theme,
                     row: float, offset: float, size: float | None = None,
                     color: Color | None = None, across: bool = False,
                     tag: Any = None) -> TextMark:
    """One track caption, placed through the projector like any band content.

    *across* turns the glyph run through a right angle so that it crosses the
    band instead of following it -- vertical beside a rectangular tree,
    tangential to the rings in a fan.  That is what a caption wider than its
    own column has to do: along the band it can only spill sideways, and
    sideways is the neighbouring track's header.

    The anchor is centred on both axes, which is what makes the half turn in
    :func:`_upright` free: it maps the text box onto itself, so a fan's
    captions can be kept the right way up without moving them.
    """
    place = projector.text(row, offset, Anchor.MIDDLE, rotate=projector.is_polar)
    rotation = _upright(place.rotation - 90.0) if across else place.rotation
    style = TextStyle(family=theme.font_family,
                      size=float(size or theme.track_title_size),
                      color=color if color is not None else theme.muted,
                      anchor=Anchor.MIDDLE, baseline=Baseline.MIDDLE)
    return TextMark(x=place.x, y=place.y, text=title, style=style,
                    rotation=rotation, tag=tag)


def _upright(degrees: float) -> float:
    """*degrees* folded into ``[-90, 90)`` so the text never reads upside down.

    Folding modulo a half turn is exactly right for a centred text box: half a
    turn maps the box onto itself, so the glyphs turn over while the geometry
    the packing pass reserved does not move.
    """
    return (degrees + 90.0) % 180.0 - 90.0


def _header_budget(proj: "Projector") -> float:
    """Rows of header the layout leaves free before it wraps onto the data.

    A rectangular tree grows its page instead of running out, so its budget is
    unbounded.  A fan has exactly the wedge its arc leaves open: row ``-g`` and
    row ``n_rows - g`` are the same place on the page, so a caption pushed past
    the gap is drawn on top of the LAST tips' tracks.  That is what laid "Gene
    presence" across the gene columns of the manuscript's Figure 2.
    """
    if not proj.is_polar:
        return math.inf
    arc = abs(float(getattr(proj, "arc", 360.0)))
    if arc <= _ANGLE_EPS or arc >= 360.0 - _ANGLE_EPS:
        return 0.0
    return (360.0 - arc) / arc * proj.n_rows


def _emit_track_titles(scene: Scene, frame: LayoutFrame, theme: Theme,
                       metrics: TextMetrics,
                       stack: Sequence[tuple["Track", float, float]],
                       sink: DiagnosticSink | None = None) -> None:
    """Draw the whole header row, once the stack has been measured.

    Tracks used to caption themselves, and a caption is centred over a track
    that may be thinner than the word: a 14 unit colour strip titled
    "Biogeographic region" laid its caption straight across its neighbour's
    header.  No track can fix that alone -- it does not know its neighbours
    exist -- so the compositor does it here, where the whole stack is known and
    the header can be solved in one pass.

    A fan's header is also the only one that can run out of room, and a caption
    that was dropped for want of it is reported rather than left as a track the
    reader cannot name.
    """
    proj = frame.projector
    if proj is None or not stack:
        return
    blocked = _header_obstacles(scene, proj, metrics)
    boxes, dropped = _plan_track_titles(frame, proj, theme, metrics, stack,
                                        blocked)
    for box in boxes:
        scene.add(draw_track_title(
            box.text, projector=proj, theme=theme,
            row=-(box.depth + 0.5 * box.rows), offset=box.offset,
            size=box.size, across=box.across, tag=box.track_id), Layer.TRACKS)
    if dropped and sink is not None:
        sink.warn("compose.track-title-no-room",
                  f"{len(dropped)} track title(s) had no room in the gap this "
                  f"{abs(float(getattr(proj, 'arc', 360.0))):g} degree fan "
                  f"leaves open, and were not drawn: "
                  f"{', '.join(repr(t) for t in dropped)}; a smaller arc "
                  f"widens the gap, and the legend names every track either way")


def _band_of(proj: "Projector", x: float, y: float) -> tuple[float, float]:
    """Inverse of :meth:`~makeyourtree.layout.projector.Projector.point`.

    The projector maps band space out; nothing maps it back, and the header
    solver needs the return trip in order to reason about marks the TRACKS
    themselves already put above the band -- a bar chart's value-axis labels,
    for one -- in the coordinates it packs in.
    """
    if not proj.is_polar:
        row_height = getattr(proj, "row_height", 0.0) or 1.0
        return ((y - getattr(proj, "top_y", 0.0)) / row_height,
                x - _base_along(proj))
    dx, dy = x - proj.cx, y - proj.cy
    span = proj.arc * proj.direction
    if abs(span) < _EPS or proj.n_rows <= 0:
        row = 0.0
    else:
        delta = (math.degrees(math.atan2(dy, dx)) - proj.start_angle
                 + 180.0) % 360.0 - 180.0
        row = delta / span * proj.n_rows
    return (row, math.hypot(dx, dy) - proj.base_r)


def _header_obstacles(scene: Scene, proj: "Projector", metrics: TextMetrics
                      ) -> list[tuple[float, float, float, float]]:
    """``(near, far, depth0, depth1)`` for every track mark sitting above the band.

    A track may write its own header content -- the bar chart labels its value
    axis one row before the first tip -- and that content is emitted before the
    captions are placed.  Treating it as already-occupied is what stops a
    caption being dropped on top of its OWN track's axis labels, which is the
    same defect one column over.

    Only text is collected: a track's rules and cells live inside the band, and
    a grid line crossed by a caption is a cosmetic detail, not a legibility
    failure.
    """
    blocked: list[tuple[float, float, float, float]] = []
    stack: list[Mark] = list(scene.layers.get(Layer.TRACKS, ()))
    while stack:
        mark = stack.pop()
        if isinstance(mark, GroupMark):
            stack.extend(mark.marks)
            continue
        if not isinstance(mark, TextMark) or not mark.text:
            continue
        # Cheap reject before measuring: a track that labels its tips emits one
        # string per row, and none of them can reach the header.
        if _band_of(proj, mark.x, mark.y)[0] >= 1.0:
            continue
        x0, y0, x1, y1 = _text_bounds(mark, metrics)
        rows: list[float] = []
        offs: list[float] = []
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            row, off = _band_of(proj, x, y)
            rows.append(row)
            offs.append(off)
        if min(rows) >= 0.0:
            continue
        # A mark straddling the first tip row blocks only the part of itself
        # that is actually in the header.
        blocked.append((min(offs) - 0.5 * HEADER_PAD, max(offs) + 0.5 * HEADER_PAD,
                        max(0.0, -max(rows)), -min(rows)))
    return blocked


def _title_geometry(frame: LayoutFrame, proj: "Projector", *, width: float,
                    height: float, mid: float, across: bool
                    ) -> tuple[float, float, float]:
    """``(span, rows, per_row)`` for one caption orientation, in band space.

    *span* is the caption's extent along the offset axis; *rows* is its extent
    along the row axis expressed in tip rows, which is the unit the header is
    packed and budgeted in.  Both orientations are measured through this one
    function so that choosing between them compares like with like.
    """
    run, span = (width, height) if across else (height, width)
    if across and proj.is_polar:
        # A turned caption in a fan is a CHORD of its ring, so its ends dip
        # inward by the sagitta.  Twice that, added to the span, keeps the
        # reserved slab symmetric about the caption and never short.
        radius = _base_along(proj) + mid
        if radius > _EPS:
            span += run * run / (4.0 * radius)
    # In a fan a row is narrower the closer to the centre it is measured, so
    # the row budget is taken at the innermost point the caption reaches.
    per_row = proj.tangential(max(0.0, mid - 0.5 * span))
    if per_row <= _EPS:
        per_row = frame.row_height if frame.row_height > _EPS else 1.0
    return span, run / per_row, per_row


def _plan_track_titles(frame: LayoutFrame, proj: "Projector", theme: Theme,
                       metrics: TextMetrics,
                       stack: Sequence[tuple["Track", float, float]],
                       blocked: Sequence[tuple[float, float, float, float]] = ()
                       ) -> tuple[list[_TitleBox], list[str]]:
    """Measure every visible caption and pack it into the header it has.

    Four escalating remedies, in the order a typographer reaches for them:
    keep the caption along its own column while it fits there; turn it across
    the band when it does not; turn it back again when the band it would cross
    is a fan's narrow gap, since a radial caption costs only the font's height
    in rows; and cut it when neither orientation fits.  Whichever orientation a
    caption ends up in, :func:`_pack_header_rows` is what guarantees the
    result: no two captions share both an offset range and a header row, and
    none is placed past the budget.

    Returns the boxes to draw and the titles of the tracks left uncaptioned.  A
    caption that simply vanishes looks like a track nobody asked for, so the
    second list exists to be reported.
    """
    budget = _header_budget(proj)
    clearance = (HEADER_GAP_ROWS if math.isinf(budget)
                 else min(HEADER_GAP_ROWS, HEADER_GAP_SHARE * budget))
    room = budget - clearance
    titles: dict[str, str] = {}
    boxes: list[_TitleBox] = []
    dropped: list[str] = []
    for track, offset, thickness in stack:
        if not track.opt("show_title", True):
            continue
        text = str(track.title or "")
        # A caption floating beside a column that drew nothing says nothing and
        # only crowds the next track.
        if not text or not track.data.rows:
            continue
        titles[track.id] = text
        size = float(track.opt("title_size") or theme.track_title_size)
        family = theme.font_family
        width = metrics.advance(text, size, family=family)
        height = metrics.ascent(size, family) + metrics.descent(size, family)
        mid = offset + 0.5 * thickness
        across = width + HEADER_PAD > thickness
        if across and width > MAX_HEADER_DEPTH:
            text = metrics.ellipsize(text, size, MAX_HEADER_DEPTH, family=family)
            width = metrics.advance(text, size, family=family)
        if not text:
            continue
        span, rows, per_row = _title_geometry(
            frame, proj, width=width, height=height, mid=mid, across=across)
        if rows > room:
            turned = _title_geometry(frame, proj, width=width, height=height,
                                     mid=mid, across=not across)
            if turned[1] <= room:
                # Radially the caption reaches past the track it names, which
                # is why it is not the first choice; but in the gap there is
                # nothing beside it except other captions, and the packer keeps
                # those apart.
                across = not across
                span, rows, per_row = turned
            elif across and room > 0.0:
                text = metrics.ellipsize(text, size, room * per_row,
                                         family=family)
                width = metrics.advance(text, size, family=family)
                span, rows, per_row = _title_geometry(
                    frame, proj, width=width, height=height, mid=mid,
                    across=across)
        if not text.strip("\u2026 ") or rows > room:
            dropped.append(titles[track.id])
            continue
        boxes.append(_TitleBox(track_id=track.id, text=text, size=size,
                               offset=mid, span=span, rows=rows, across=across))
    kept = _pack_header_rows(boxes, blocked, clearance=clearance, budget=budget)
    fitted = {id(box) for box in kept}
    dropped.extend(titles[box.track_id] for box in boxes
                   if id(box) not in fitted)
    return kept, dropped


def _pack_header_rows(boxes: list[_TitleBox],
                      blocked: Sequence[tuple[float, float, float, float]] = (),
                      *, clearance: float = HEADER_GAP_ROWS,
                      budget: float = math.inf) -> list[_TitleBox]:
    """Greedy first-fit outward, in place; returns the boxes that fitted.

    Each caption starts on the header row nearest the tips and is pushed one
    row further out for as long as it still overlaps something already there --
    an earlier caption, or a *blocked* rectangle a track drew for itself.
    Depth only ever increases and there are finitely many obstacles, so the
    sweep terminates; and because a box is only ever pushed clear of something
    it actually clashed with, the packing is collision-free by construction
    rather than by inspection.

    *budget* is where the header runs out.  It is unbounded beside a
    rectangular tree, whose page simply grows; in a fan it is the gap the arc
    leaves open, where one row further out is one row INTO the last tips'
    tracks.  A caption that would be pushed past it is not drawn at all --
    there is no free header row in a nearly closed fan.
    """
    placed: list[tuple[float, float, float, float]] = list(blocked)
    kept: list[_TitleBox] = []
    for box in boxes:
        depth = clearance
        for _ in range(len(boxes) + len(placed) + 1):
            pushed = False
            for near, far, d0, d1 in placed:
                if box.far <= near or box.near >= far:
                    continue
                if depth < d1 and depth + box.rows > d0:
                    depth = d1 + HEADER_PAD_ROWS
                    pushed = True
            if not pushed:
                break
        if depth + box.rows > budget + _EPS:
            continue
        box.depth = depth
        kept.append(box)
        placed.append((box.near, box.far, depth, depth + box.rows))
    return kept


# ---------------------------------------------------------------- branches


def _branch_style_walk(document: "Document", theme: Theme):
    """Yield ``(node, effective_branch_style)`` over the visible tree.

    Equivalent to calling :func:`makeyourtree.style.theme.resolve` per node for the
    inherited branch keys, but O(n) instead of O(n x depth): the inherited dict
    is carried down the explicit stack rather than rebuilt by walking back up to
    the root at every node.
    """
    base = {"branch_color": theme.branch_color,
            "branch_width": theme.branch_width,
            "branch_dash": None,
            "branch_opacity": 1.0}
    root = document.tree.root
    if root.hidden:
        return
    stack: list[tuple[Node, dict[str, Any]]] = [(root, base)]
    while stack:
        node, inherited = stack.pop()
        effective = inherited
        if node.style:
            override = {k: v for k, v in node.style.items() if k in INHERITED_KEYS}
            if override:
                effective = dict(inherited)
                effective.update(override)
        yield node, effective
        if node.collapsed:
            continue
        for child in reversed(node.children):
            if not child.hidden:
                stack.append((child, effective))


def _branch_paint(style: dict[str, Any], theme: Theme) -> tuple[tuple, Paint]:
    color = _as_color(style.get("branch_color"), theme.branch_color)
    width = float(style.get("branch_width") or theme.branch_width)
    dash = _as_dash(style.get("branch_dash"))
    opacity = float(style.get("branch_opacity", 1.0) or 0.0)
    key = (color, width, dash, opacity)
    return key, Paint(stroke=color, width=width, dash=dash, opacity=opacity,
                      cap=Cap.BUTT, join=Join.ROUND, cosmetic=theme.branch_cosmetic)


def _emit_branches(scene: Scene, document: "Document", frame: LayoutFrame,
                   params: LayoutParams, theme: Theme) -> None:
    """Emit every visible edge, bucketed by resolved paint.

    Geometry is re-derived from the frame's node positions rather than read from
    ``frame.straight``, because the flat edge list carries no node identity and
    so cannot be split by style.  Both come from the same coordinates, so they
    agree.
    """
    polar = params.mode.is_polar
    elbow = params.mode is LayoutMode.RECTANGULAR
    cx, cy = frame.center

    lines: dict[tuple, list[float]] = {}
    arcs: dict[tuple, list[tuple]] = {}
    paints: dict[tuple, Paint] = {}

    for node, style in _branch_style_walk(document, theme):
        parent = node.parent
        if parent is None or not frame.has(node.id) or not frame.has(parent.id):
            continue
        key, paint = _branch_paint(style, theme)
        if key not in paints:
            paints[key] = paint
        nx, ny = frame.xy(node.id)
        px, py = frame.xy(parent.id)
        if polar:
            pr = frame.radius(parent.id)
            pa = frame.angle(parent.id)
            na = frame.angle(node.id)
            sx = cx + pr * math.cos(math.radians(na))
            sy = cy + pr * math.sin(math.radians(na))
            lines.setdefault(key, []).extend((sx, sy, nx, ny))
            if abs(na - pa) > _ANGLE_EPS and pr > _EPS:
                arcs.setdefault(key, []).append((cx, cy, pr, pa, na))
        elif elbow:
            bucket = lines.setdefault(key, [])
            if abs(py - ny) > _EPS:
                bucket.extend((px, py, px, ny))
            bucket.extend((px, ny, nx, ny))
        else:
            lines.setdefault(key, []).extend((px, py, nx, ny))

    for key, coords in lines.items():
        if coords:
            scene.add(LinesMark(paint=paints[key], coords=coords), Layer.BRANCHES)
    for key, items in arcs.items():
        segments: list[tuple] = []
        for acx, acy, r, a0, a1 in items:
            segments.append(("M", acx + r * math.cos(math.radians(a0)),
                             acy + r * math.sin(math.radians(a0))))
            segments.append(("A", acx, acy, r, a0, a1, a1 < a0))
        stroke_only = Paint(fill=None, stroke=paints[key].stroke,
                            width=paints[key].width, dash=paints[key].dash,
                            opacity=paints[key].opacity, cap=Cap.BUTT,
                            join=Join.ROUND, cosmetic=theme.branch_cosmetic)
        scene.add(PathMark(paint=stroke_only, segments=tuple(segments)),
                  Layer.BRANCHES)


# ------------------------------------------------------------- clade fills


def _emit_clade_fills(scene: Scene, document: "Document", frame: LayoutFrame,
                      theme: Theme,
                      stack: Sequence[tuple["Track", float, float]]) -> None:
    """Wash the row band of any clade carrying an explicit ``clade_fill``.

    Painted into ``Layer.UNDERLAY`` so branch strokes stay legible on top, and
    extended across the track stack so the highlight reads as one column.
    """
    proj = frame.projector
    if proj is None:
        return
    far = 0.0
    if stack:
        track, offset, thickness = stack[-1]
        far = offset + thickness
    far = max(far, frame.tip_offset)

    rects: list[float] = []
    fills: list[Color] = []
    for node in document.tree.nodes:
        if not node.style or node.hidden:
            continue
        raw = node.style.get("clade_fill")
        if raw is None or not frame.has(node.id):
            continue
        color = _as_color(raw, theme.accent)
        lo, hi = frame.row_span(node.id)
        if hi <= lo:
            continue
        near = min(0.0, _offset_of(frame, proj, node.id))
        box = proj.rect(lo, hi, near, far)
        if box is None:
            scene.add(PathMark(paint=Paint.filled(color),
                               segments=proj.cell(lo, hi, near, far),
                               tag=node.id), Layer.UNDERLAY)
        else:
            rects.extend(box)
            fills.append(color)
    if rects:
        scene.add(RectsMark(paint=Paint(fill=None, stroke=None),
                            coords=rects, fills=fills), Layer.UNDERLAY)
    _emit_clade_labels(scene, document, frame, theme, far)


def _emit_clade_labels(scene: Scene, document: "Document", frame: LayoutFrame,
                       theme: Theme, far: float) -> None:
    """A name for a whole clade, set beyond the track stack against its rows.

    ``clade_label`` is a :class:`~makeyourtree.style.theme.NodeStyle` key that
    nothing consumed: it could be set and it survived a save, but no text was
    ever drawn.  It is placed through ``projector.text`` at the clade's middle
    row, so a fan rotates and flips it onto its own radius like any tip label
    rather than leaving it lying flat across the rings.
    """
    proj = frame.projector
    if proj is None:
        return
    gap = theme.track_margin
    for node in document.tree.nodes:
        if not node.style or node.hidden or not frame.has(node.id):
            continue
        text = node.style.get("clade_label")
        if not text:
            continue
        lo, hi = frame.row_span(node.id)
        if hi <= lo:
            continue
        place = proj.text((lo + hi) * 0.5, far + gap, Anchor.START,
                          rotate=proj.is_polar)
        style = TextStyle(family=theme.font_family, size=theme.track_title_size,
                          weight=600, color=theme.effective_label_color(),
                          anchor=place.anchor, baseline=Baseline.MIDDLE)
        scene.add(TextMark(x=place.x, y=place.y, text=str(text), style=style,
                           rotation=place.rotation, tag=node.id), Layer.LABELS)


# --------------------------------------------------------- collapsed clades


def _emit_collapsed(scene: Scene, document: "Document", frame: LayoutFrame,
                    params: LayoutParams, theme: Theme) -> None:
    """Summary glyph for every collapsed clade.

    The geometry is not computed here.  ``layout.collapse.collapse_outline``
    owns it, works in band space, and reads the same cached tip-depth
    statistics the layout used to reserve room for the glyph -- so the shape
    and the space it was given cannot disagree.  What is left is projection and
    paint, plus the choice of the cheapest mark that can carry the result.
    """
    from ..layout.collapse import collapse_outline

    proj = frame.projector
    if proj is None:
        return

    for node_id in frame.tips:
        node = document.tree.by_id(node_id)
        if node is None or not node.collapsed or not node.children:
            continue
        lo, hi = frame.row_span(node_id)
        if hi <= lo:
            continue
        outline = collapse_outline(node, frame, params)
        if len(outline) < 3:
            continue

        fill = _as_color((node.style or {}).get("clade_fill"), theme.collapse_fill)
        paint = Paint(fill=fill, stroke=theme.collapse_stroke, width=0.8,
                      join=Join.ROUND)
        mark = _collapsed_mark(outline, frame, proj, paint, node_id)
        if mark is not None:
            scene.add(mark, Layer.COLLAPSED)


def _collapsed_mark(outline: Sequence, frame: LayoutFrame, proj: "Projector",
                    paint: Paint, node_id: int) -> "Mark | None":
    """Project a band-space outline into the cheapest mark that fits it.

    Three cases, in increasing cost.  A band-space rectangle under a projector
    that offers :meth:`~makeyourtree.layout.projector.Projector.rect` is a
    ``RectMark``.  Anything else in a linear frame is straight-sided, so a
    ``PolygonMark`` carries it exactly.  In a polar frame an edge at constant
    ``along`` is an ARC, not a chord: a collapsed clade spanning a tenth of a
    fan drawn with a straight base is visibly a triangle sitting inside the
    ring rather than a wedge of it, so those edges become real arc segments and
    the result is a ``PathMark``.
    """
    base = _base_along(proj)
    pts = [(seg[1], seg[2]) for seg in outline if seg[0] in ("M", "L")]
    if len(pts) < 3:
        return None

    rows = [r for r, _ in pts]
    alongs = [a for _, a in pts]
    row0, row1 = min(rows), max(rows)
    off0, off1 = min(alongs) - base, max(alongs) - base
    is_box = len(pts) == 4 and len(set(rows)) == 2 and len(set(alongs)) == 2
    if is_box:
        box = proj.rect(row0, row1, off0, off1)
        if box is not None:
            return RectMark(paint=paint, x=box[0], y=box[1], w=box[2], h=box[3],
                            tag=node_id)
        return PathMark(paint=paint, segments=proj.cell(row0, row1, off0, off1),
                        tag=node_id)

    if not proj.is_polar:
        flat: list[float] = []
        for row, along in pts:
            x, y = proj.point(row, along - base)
            flat.extend((x, y))
        return PolygonMark(paint=paint, points=flat, tag=node_id)

    path = Path()
    path.move_to(*proj.point(pts[0][0], pts[0][1] - base))
    for i in range(1, len(pts) + 1):
        r_prev, a_prev = pts[i - 1]
        r_next, a_next = pts[i % len(pts)]
        if a_next == a_prev and r_next != r_prev:
            radius = a_prev - base + proj.base_r
            a0, a1 = proj.angle_of(r_prev), proj.angle_of(r_next)
            path.arc(proj.cx, proj.cy, radius, a0, a1, a1 < a0)
        else:
            path.line_to(*proj.point(r_next, a_next - base))
    return PathMark(paint=paint, segments=path.close().freeze(), tag=node_id)


# ------------------------------------------------------------------ labels


def _own_label_style(node: Node, theme: Theme,
                     internal: bool) -> tuple[str | None, float, Color, bool, bool]:
    """Label text and appearance for one node.

    Label keys are deliberately *not* inherited (see
    :data:`makeyourtree.style.theme.INHERITED_KEYS`), so only the node's own
    overrides matter and no ancestor walk is needed.
    """
    style = node.style or {}
    if style.get("label_hidden"):
        return (None, 0.0, theme.foreground, False, False)
    text = style.get("label_text") or node.name
    size = float(style.get("label_size")
                 or (theme.internal_label_size if internal else theme.label_size))
    default = (theme.effective_internal_label_color() if internal
               else theme.effective_label_color())
    color = _as_color(style.get("label_color"), default)
    return (text, size, color, bool(style.get("label_bold")),
            bool(style.get("label_italic")))


def _emit_labels(scene: Scene, document: "Document", frame: LayoutFrame,
                 params: LayoutParams, theme: Theme,
                 metrics: TextMetrics) -> None:
    proj = frame.projector
    tree = document.tree
    rotate = params.rotate_labels and proj is not None and proj.is_polar

    if params.show_tip_labels:
        for node_id in frame.tips:
            node = tree.by_id(node_id)
            if node is None or not frame.has(node_id):
                continue
            text, size, color, bold, italic = _own_label_style(node, theme, False)
            if not text:
                continue
            if params.max_label_width:
                text = metrics.ellipsize(text, size, params.max_label_width,
                                         bold=bold, italic=italic)
                if not text:
                    continue
            offset = (0.0 if params.align_tips
                      else _offset_of(frame, proj, node_id)) + params.tip_label_gap
            _add_text(scene, frame, proj, node_id, text, offset, size, color,
                      bold, italic, theme, Anchor.START, rotate, Layer.LABELS,
                      params.max_label_width)

    if params.show_internal_labels:
        for node in _visible_nodes(document):
            if node.is_tip or not frame.has(node.id):
                continue
            text, size, color, bold, italic = _own_label_style(node, theme, True)
            if not text:
                continue
            offset = _offset_of(frame, proj, node.id) - params.tip_label_gap
            _add_text(scene, frame, proj, node.id, text, offset, size, color,
                      bold, italic, theme, Anchor.END, rotate, Layer.LABELS,
                      None)


def _add_text(scene: Scene, frame: LayoutFrame, proj: Projector | None,
              node_id: int, text: str, offset: float, size: float, color: Color,
              bold: bool, italic: bool, theme: Theme, anchor: Anchor,
              rotate: bool, layer: Layer, max_width: float | None) -> None:
    """Place one node-owned label, in band space when a projector exists."""
    style = TextStyle(family=theme.font_family, size=size,
                      weight=600 if bold else 400, italic=italic, color=color,
                      anchor=anchor, baseline=Baseline.MIDDLE)
    if proj is None:
        x, y = _free_placement(frame, node_id, offset)
        scene.add(TextMark(x=x, y=y, text=text, style=style, tag=node_id,
                           max_width=max_width), layer)
        return
    placement = proj.text(frame.row(node_id), offset, anchor, rotate=rotate)
    scene.add(TextMark(x=placement.x, y=placement.y, text=text,
                       style=dataclasses.replace(style, anchor=placement.anchor),
                       rotation=placement.rotation, tag=node_id,
                       max_width=max_width), layer)


def _free_placement(frame: LayoutFrame, node_id: int,
                    offset: float) -> tuple[float, float]:
    """Fallback placement for a layout with no band projector.

    Unrooted drawings place nodes in the plane directly and have no band space
    at all, so the label simply sits to the right of its node.
    """
    x, y = frame.xy(node_id)
    return (x + max(offset, 0.0), y)


# ------------------------------------------------------------ support values


def _emit_support(scene: Scene, document: "Document", frame: LayoutFrame,
                  theme: Theme) -> None:
    """Branch support, as text beside the node or as a sized marker on it.

    Support belongs to the edge ``parent -> node`` (see
    :mod:`makeyourtree.core.node`), so it is drawn at the node's own end of that
    edge, which is where a reader looks for it.
    """
    if not theme.show_support:
        return
    proj = frame.projector
    position = (theme.support_position or "above").lower()
    style = TextStyle(family=theme.font_family, size=theme.support_size,
                      color=theme.support_color, anchor=Anchor.END,
                      baseline=Baseline.MIDDLE)
    marker_paint = Paint(fill=theme.support_color, stroke=None)
    span = document.tree.support_range()
    lo, hi = span if span else (0.0, 1.0)

    for node in _visible_nodes(document):
        if node.support is None or node.parent is None or not frame.has(node.id):
            continue
        if theme.support_min is not None and node.support < theme.support_min:
            continue
        x, y = frame.xy(node.id)
        if position == "node":
            frac = 0.0 if hi <= lo else (node.support - lo) / (hi - lo)
            r = theme.support_size * (0.25 + 0.35 * max(0.0, min(1.0, frac)))
            scene.add(EllipseMark(paint=marker_paint, cx=x, cy=y, rx=r, ry=r,
                                  tag=node.id), Layer.DECOR)
            continue
        ox, oy = (1.0, 0.0)
        if proj is not None and proj.is_polar:
            ox, oy = proj.outward(frame.row(node.id))
        # Perpendicular to the outward direction: (1,0) -> (0,-1), i.e. "up".
        px, py = (oy, -ox)
        if position == "below":
            px, py = (-px, -py)
        pad = theme.support_size * 0.55
        scene.add(TextMark(
            x=x - ox * 2.0 + px * pad, y=y - oy * 2.0 + py * pad,
            text=theme.support_format.format(node.support),
            style=style, tag=node.id), Layer.DECOR)


# ------------------------------------------------------------- guide lines


def _emit_guides(scene: Scene, frame: LayoutFrame, params: LayoutParams,
                 theme: Theme) -> None:
    """Dotted leaders from each tip to the label column.

    Only meaningful when tips are aligned: without alignment the label already
    starts at the tip and there is nothing to bridge.
    """
    if not (params.align_tips and params.guide_lines):
        return
    proj = frame.projector
    if proj is None:
        return
    coords = _guide_coords(frame, proj)
    if coords:
        scene.add(LinesMark(
            paint=Paint(fill=None, stroke=theme.guide_color,
                        width=theme.guide_width, dash=tuple(theme.guide_dash),
                        cap=Cap.BUTT),
            coords=coords), Layer.GRID)


def _guide_coords(frame: LayoutFrame, proj: "Projector") -> list[float]:
    """Flat ``x0, y0, x1, y1`` leader geometry, from the layout where it has it.

    A layout that solved for aligned tips already knows where each leader has
    to start: past a collapsed clade's summary glyph, past the label gap, and
    only when the remaining run is long enough to read as a leader rather than
    as a smudge.  It publishes that as ``metadata["guides"]`` in scene
    coordinates -- identical in the linear and polar families -- so preferring
    it keeps one rule instead of two that drift apart.

    The band-space derivation below is the fallback for a frame that offers a
    projector but no guide geometry (an unrooted drawing, or a third-party
    :class:`~makeyourtree.layout.frame.Layout`).
    """
    published = frame.metadata.get("guides")
    if published is not None:
        return [float(v) for v in published]
    coords: list[float] = []
    for node_id in frame.tips:
        if not frame.has(node_id):
            continue
        offset = _offset_of(frame, proj, node_id)
        if offset > -0.5:
            continue
        row = frame.row(node_id)
        x0, y0 = proj.point(row, offset)
        x1, y1 = proj.point(row, 0.0)
        coords.extend((x0, y0, x1, y1))
    return coords


# ------------------------------------------------------------ node markers


def _emit_node_markers(scene: Scene, document: "Document", frame: LayoutFrame,
                       theme: Theme) -> None:
    """Glyphs for nodes carrying ``marker_shape`` in their style.

    :class:`~makeyourtree.style.theme.NodeStyle` documents ``marker_shape`` as "one
    of the shapes in :data:`makeyourtree.tracks.shapes.SHAPES`", which names both
    ends of a seam that nothing was actually joining: a user could set the key,
    it round-tripped through the project file, and no mark was ever drawn.

    The shapes registry works in band space, so it is asked for the glyph at
    the node's own ``(row, offset)`` and the projector supplies the rest.  That
    is what makes a triangle point away from the tree in a fan as well as in a
    rectangle, with no branch here on layout mode.  Marker keys are not
    inherited (they are absent from
    :data:`~makeyourtree.style.theme.INHERITED_KEYS`), so only a node's own style
    is consulted and no ancestor walk is needed.
    """
    proj = frame.projector
    if proj is None:
        return
    from ..tracks.shapes import band_offset_of, is_open_shape, shape_path

    for node in _visible_nodes(document):
        style = node.style or {}
        shape = style.get("marker_shape")
        if not shape or not frame.has(node.id):
            continue
        # Theme is frozen and carries no node-marker size.  ``support_size``
        # is the size of the other glyph drawn ON a node, so borrowing it keeps
        # the two node decorations consistent and scales both with one setting.
        size = float(style.get("marker_size") or theme.support_size)
        if size <= 0.0:
            continue
        fill = _as_color(style.get("marker_color"), theme.branch_color)
        stroke = style.get("marker_stroke")
        open_shape = is_open_shape(str(shape))
        paint = Paint(
            fill=None if open_shape else fill,
            stroke=_as_color(stroke, fill) if (stroke or open_shape) else None,
            width=max(theme.branch_width, 1.0) if (stroke or open_shape) else 0.0,
            join=Join.ROUND)
        segments = shape_path(str(shape), frame.row(node.id),
                              band_offset_of(frame, proj, node.id),
                              size * 0.5, proj)
        if segments:
            scene.add(PathMark(paint=paint, segments=segments, tag=node.id),
                      Layer.DECOR)


# ------------------------------------------------------- scale bar and axis


def _emit_scalebar(scene: Scene, frame: LayoutFrame, params: LayoutParams,
                   theme: Theme, metrics: TextMetrics) -> None:
    """Draw the bar ``layout.scalebar`` sized, or nothing when it returned None.

    The rounding, the minimum readable length, the clamp that stops one outlier
    tip producing a bar longer than the tree, and -- most importantly -- the
    decision that a bar would be a LIE all live in
    :mod:`makeyourtree.layout.scalebar`.  A second implementation here would drift
    from the tick ladder beside it, and a bar built from ``branch_mode`` alone
    prints a length on a RADIAL fan, whose along axis is topological.
    """
    from ..layout.scalebar import scale_bar

    bar = scale_bar(frame, params, theme)
    if bar is None or bar.pixels <= 1.0:
        return
    fs = theme.scalebar_size
    bx, by = bar.position
    proj = frame.projector
    if proj is not None and proj.is_polar:
        # The suggested anchor is the bottom-left corner of ``body_bounds``,
        # which in a fan is the SQUARE around the body: that corner lies at 1.41
        # times the body radius, which is inside the drawing -- in the tip-label
        # annulus, where the manuscript's Figure 2 had it lying across three tip
        # names.  A fan has no empty corner, so the bar goes below everything
        # already emitted; the legend has not been built yet, so this is the
        # figure's own extent and not the page's.
        x0, _, _, y1 = _scene_bounds(scene, metrics)
        bx = x0
        by = y1 + max(fs * 2.0, params.row_spacing)
    tick = fs * 0.4
    scene.add(LinesMark(
        paint=Paint(fill=None, stroke=theme.scalebar_color, width=1.0),
        coords=[bx, by, bx + bar.pixels, by,
                bx, by - tick, bx, by + tick,
                bx + bar.pixels, by - tick, bx + bar.pixels, by + tick]),
        Layer.DECOR)
    scene.add(TextMark(
        x=bx + bar.pixels * 0.5, y=by + tick + fs * 0.9, text=bar.label,
        style=TextStyle(family=theme.font_family, size=fs,
                        color=theme.scalebar_color, anchor=Anchor.MIDDLE,
                        baseline=Baseline.MIDDLE)), Layer.DECOR)
    scene.metadata["scalebar"] = (bar.units, bar.pixels)


def _emit_axis(scene: Scene, frame: LayoutFrame, params: LayoutParams,
               theme: Theme) -> None:
    """Distance grid: straight rules in linear modes, rings in polar ones.

    Tick VALUES and their along-axis positions come from
    ``layout.scalebar.axis_ticks``, which measures a polar frame from the inner
    hole and stops at the deepest tip.  Deriving them here from the body's
    bounding box -- whose width is a fan's DIAMETER -- drew rings out to twice
    the tree's radius, half of them outside the figure entirely.
    """
    from ..layout.scalebar import axis_ticks

    if not theme.axis_show:
        return
    ticks = axis_ticks(frame, params)
    if not ticks:
        return

    proj = frame.projector
    x0, y0, x1, y1 = frame.body_bounds
    label_style = TextStyle(family=theme.font_family, size=theme.scalebar_size,
                            color=theme.muted, anchor=Anchor.MIDDLE,
                            baseline=Baseline.MIDDLE)
    paint = Paint(fill=None, stroke=theme.axis_color, width=0.6)

    if proj is not None and proj.is_polar:
        cx, cy = frame.center
        segments: list[tuple] = []
        for _value, radius, _label in ticks:
            if radius <= 0:
                continue
            segments.append(("M", cx + radius, cy))
            segments.append(("A", cx, cy, radius, 0.0, 360.0, False))
        if segments:
            scene.add(PathMark(paint=paint, segments=tuple(segments)), Layer.GRID)
        return

    coords: list[float] = []
    for _value, x, label in ticks:
        coords.extend((x, y0, x, y1))
        scene.add(TextMark(x=x, y=y1 + theme.scalebar_size * 0.9,
                           text=label, style=label_style), Layer.DECOR)
    if coords:
        scene.add(LinesMark(paint=paint, coords=coords), Layer.GRID)


# ------------------------------------------------------------------- bounds


def _union(a: "Bounds", b: "Bounds") -> "Bounds":
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _scene_bounds(scene: Scene, metrics: TextMetrics) -> "Bounds":
    """Extent of every non-overlay mark, text included.

    Text is measured rather than guessed, so a long tip label cannot fall off
    the page: this is the number the page size is derived from.
    """
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for mark in scene.iter_marks(include_overlay=False):
        box = _mark_bounds(mark, metrics)
        if box is None:
            continue
        x0 = min(x0, box[0])
        y0 = min(y0, box[1])
        x1 = max(x1, box[2])
        y1 = max(y1, box[3])
    if x0 > x1 or y0 > y1:
        return (0.0, 0.0, 0.0, 0.0)
    return (x0, y0, x1, y1)


def _pad(box: "Bounds", paint: Paint) -> "Bounds":
    half = paint.width * 0.5 if (paint.stroke is not None and paint.width > 0) else 0.0
    return (box[0] - half, box[1] - half, box[2] + half, box[3] + half)


def _flat_bounds(flat: Sequence[float]) -> "Bounds" | None:
    """Extent of a flat ``x, y, x, y, ...`` coordinate run."""
    if len(flat) < 2:
        return None
    xs = flat[0::2]
    ys = flat[1::2]
    return (min(xs), min(ys), max(xs), max(ys))


def _mark_bounds(mark: Mark, metrics: TextMetrics) -> "Bounds" | None:
    if isinstance(mark, LinesMark) or isinstance(mark, PolylineMark) or \
            isinstance(mark, PolygonMark):
        flat = mark.coords if isinstance(mark, LinesMark) else mark.points
        box = _flat_bounds(flat)
        return None if box is None else _pad(box, mark.paint)
    if isinstance(mark, RectMark):
        x, y = min(mark.x, mark.x + mark.w), min(mark.y, mark.y + mark.h)
        return _pad((x, y, x + abs(mark.w), y + abs(mark.h)), mark.paint)
    if isinstance(mark, RectsMark):
        c = mark.coords
        if len(c) < 4:
            return None
        xs: list[float] = []
        ys: list[float] = []
        for i in range(0, len(c) - 3, 4):
            xs.extend((c[i], c[i] + c[i + 2]))
            ys.extend((c[i + 1], c[i + 1] + c[i + 3]))
        return _pad((min(xs), min(ys), max(xs), max(ys)), mark.paint)
    if isinstance(mark, EllipseMark):
        return _pad((mark.cx - mark.rx, mark.cy - mark.ry,
                     mark.cx + mark.rx, mark.cy + mark.ry), mark.paint)
    if isinstance(mark, ImageMark):
        return (mark.x, mark.y, mark.x + mark.w, mark.y + mark.h)
    if isinstance(mark, TextMark):
        return _text_bounds(mark, metrics)
    if isinstance(mark, PathMark):
        return _path_bounds(mark)
    if isinstance(mark, GroupMark):
        acc: "Bounds | None" = None
        for child in mark.marks:
            box = _mark_bounds(child, metrics)
            if box is None:
                continue
            shifted = (box[0] + mark.dx, box[1] + mark.dy,
                       box[2] + mark.dx, box[3] + mark.dy)
            acc = shifted if acc is None else _union(acc, shifted)
        return acc
    return None


def _text_bounds(mark: TextMark, metrics: TextMetrics) -> "Bounds":
    st = mark.style
    w = metrics.advance(mark.text, st.size, bold=st.weight >= 600,
                        italic=st.italic, family=st.family)
    asc = metrics.ascent(st.size, st.family)
    desc = metrics.descent(st.size, st.family)
    if st.anchor is Anchor.MIDDLE:
        left = -w * 0.5
    elif st.anchor is Anchor.END:
        left = -w
    else:
        left = 0.0
    if st.baseline is Baseline.MIDDLE:
        top = -(asc + desc) * 0.5
    elif st.baseline is Baseline.HANGING:
        top = 0.0
    else:
        top = -asc
    corners = [(left, top), (left + w, top),
               (left, top + asc + desc), (left + w, top + asc + desc)]
    if mark.rotation:
        a = math.radians(mark.rotation)
        ca, sa = math.cos(a), math.sin(a)
        corners = [(dx * ca - dy * sa, dx * sa + dy * ca) for dx, dy in corners]
    xs = [mark.x + dx for dx, _ in corners]
    ys = [mark.y + dy for _, dy in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _path_bounds(mark: PathMark) -> "Bounds" | None:
    """Conservative path extent.

    Bezier control points and full arc circles over-estimate rather than solve
    for true extrema: the result only sizes the page, where a few units of slack
    costs nothing and a miss would crop the figure.
    """
    xs: list[float] = []
    ys: list[float] = []
    for seg in mark.segments:
        op = seg[0]
        if op in ("M", "L"):
            xs.append(seg[1])
            ys.append(seg[2])
        elif op == "Q":
            xs.extend((seg[1], seg[3]))
            ys.extend((seg[2], seg[4]))
        elif op == "C":
            xs.extend((seg[1], seg[3], seg[5]))
            ys.extend((seg[2], seg[4], seg[6]))
        elif op == "A":
            cx, cy, r = seg[1], seg[2], seg[3]
            xs.extend((cx - r, cx + r))
            ys.extend((cy - r, cy + r))
    if not xs:
        return None
    return _pad((min(xs), min(ys), max(xs), max(ys)), mark.paint)


# ------------------------------------------------------------------ sizing


def _finalise(scene: Scene, bounds: "Bounds", margin: float,
              size: tuple[float, float] | None) -> None:
    """Set the page size and, if content overhangs the origin, shift it in.

    The shift is applied as one :class:`~makeyourtree.scene.marks.GroupMark` per
    layer rather than by rewriting every coordinate: a batched mark can hold
    hundreds of thousands of floats, and translating them would cost more than
    the whole compositing pass.  The applied offset is recorded in
    ``scene.metadata["origin"]`` so hit-testing can undo it.
    """
    x0, y0, x1, y1 = bounds
    dx = margin - x0 if x0 < margin else 0.0
    dy = margin - y0 if y0 < margin else 0.0
    if dx or dy:
        for layer, marks in list(scene.layers.items()):
            if marks:
                scene.layers[layer] = [GroupMark(marks=tuple(marks), dx=dx, dy=dy)]
    scene.metadata["origin"] = (dx, dy)
    width = x1 + dx + margin
    height = y1 + dy + margin
    if size is not None:
        width = max(width, float(size[0]))
        height = max(height, float(size[1]))
    scene.width = max(width, 2.0 * margin)
    scene.height = max(height, 2.0 * margin)

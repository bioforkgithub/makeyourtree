# SPDX-License-Identifier: MIT
"""Track titles never overlap, in any layout family.

A track used to caption itself: one string, centred above its own column.  A
column can be thinner than the word above it -- a 14 unit colour strip titled
"Biogeographic region" is the reported case -- and the caption then spilled
sideways over the neighbouring track's header.  A track cannot fix that alone
because it does not know its neighbours exist, so the compositor now measures
the whole stack and lays the header row out once.

Everything here is asserted on GEOMETRY -- oriented text boxes and a separating
axis test -- never on rendered glyphs: the offscreen platform reports no font
families, so pixels say nothing.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from makeyourtree.annot.loaders import load_annotation
from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.doc.document import Document
from makeyourtree.io import load_tree
from makeyourtree.layout.params import LayoutMode, LayoutParams
from makeyourtree.scene.compose import MAX_HEADER_DEPTH, compose
from makeyourtree.scene.marks import Anchor, Baseline, GroupMark, TextMark
from makeyourtree.style.theme import Theme
from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics
from makeyourtree.tracks.strip import ColorStripTrack
from makeyourtree.tracks.base import TrackData

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
METRICS = CachedMetrics(FallbackMetrics())
_EPS = 1e-6

LONG_TITLE = ("Reconstructed ancestral biogeographic region under the "
              "dispersal-extinction-cladogenesis model")

NO_ROOM = "compose.track-title-no-room"


# --------------------------------------------------------------- geometry


def text_corners(mark: TextMark, metrics=METRICS) -> list[tuple[float, float]]:
    """The four corners of one text mark's box, in scene coordinates.

    Derived here rather than borrowed from the compositor so that the
    assertions below are a check ON the compositor rather than a restatement of
    it.  Rotation is applied about the anchor, which is what
    :class:`~makeyourtree.scene.marks.TextMark` documents.
    """
    st = mark.style
    w = metrics.advance(mark.text, st.size, bold=st.weight >= 600,
                        italic=st.italic, family=st.family)
    h = metrics.ascent(st.size, st.family) + metrics.descent(st.size, st.family)
    left = {Anchor.MIDDLE: -w * 0.5, Anchor.END: -w}.get(st.anchor, 0.0)
    top = {Baseline.MIDDLE: -h * 0.5, Baseline.HANGING: 0.0}.get(st.baseline, -h)
    local = [(left, top), (left + w, top), (left + w, top + h), (left, top + h)]
    a = math.radians(mark.rotation)
    ca, sa = math.cos(a), math.sin(a)
    return [(mark.x + dx * ca - dy * sa, mark.y + dx * sa + dy * ca)
            for dx, dy in local]


def overlaps(a, b) -> bool:
    """Separating-axis test for two convex quads.

    Oriented boxes, not axis-aligned ones: a caption turned 82 degrees in a fan
    has an axis-aligned bounding box far larger than the ink, and testing that
    would fail figures that are perfectly legible.
    """
    for poly in (a, b):
        for i in range(len(poly)):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
            nx, ny = -(y1 - y0), (x1 - x0)
            pa = [nx * x + ny * y for x, y in a]
            pb = [nx * x + ny * y for x, y in b]
            if max(pa) <= min(pb) + _EPS or max(pb) <= min(pa) + _EPS:
                return False
    return True


def test_the_separating_axis_helper_actually_detects_an_overlap():
    """A collision test that never fires would pass every case below."""
    box = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)]
    assert overlaps(box, [(5.0, 2.0), (15.0, 2.0), (15.0, 6.0), (5.0, 6.0)])
    assert not overlaps(box, [(11.0, 0.0), (20.0, 0.0), (20.0, 4.0), (11.0, 4.0)])
    turned = [(2.0, -5.0), (6.0, -5.0), (6.0, 9.0), (2.0, 9.0)]
    assert overlaps(box, turned), "a crossing pair must still be caught"


# ----------------------------------------------------------------- helpers


def flatten(scene):
    out = []
    for marks in scene.layers.values():
        stack = list(marks)
        while stack:
            mark = stack.pop()
            if isinstance(mark, GroupMark):
                stack.extend(mark.marks)
            else:
                out.append(mark)
    return out


def title_marks(scene, document) -> list[TextMark]:
    """Every mark the compositor drew as a track caption.

    Captions are tagged with their track's id, which is what lets a caller --
    the canvas, or this test -- tell a header apart from a tip label.
    """
    ids = {t.id for t in document.tracks}
    return [m for m in flatten(scene)
            if isinstance(m, TextMark) and m.tag in ids]


def composed(document):
    """Compose and keep the diagnostics: in a fan they are half the answer."""
    sink = DiagnosticSink()
    return compose(document, sink=sink), sink


def was_drawn(title: str, drawn) -> bool:
    """True when *title* is on the page, whole or cut short."""
    return any(text == title or title.startswith(text.rstrip("\u2026 "))
               for text in drawn)


def assert_every_track_is_drawn_or_reported(scene, document, sink) -> None:
    """A caption is either on the page or in the diagnostics, never neither.

    A fan's header is the wedge its arc leaves open, and that wedge can be too
    small for the captions the stack needs.  Dropping one is a legitimate
    answer to that -- drawing it across the last tips' tracks is not -- but a
    caption that simply vanishes looks like a track nobody asked for, so the
    compositor has to say which ones it could not place.
    """
    drawn = {m.text for m in title_marks(scene, document)}
    reported = " ".join(d.message for d in sink.items if d.code == NO_ROOM)
    for track in document.tracks:
        assert was_drawn(track.title, drawn) or repr(track.title) in reported, (
            f"{track.title!r} was neither drawn nor reported")


def gap_rows(frame) -> float:
    """Tip rows of header the arc leaves open, outside row zero."""
    proj = frame.projector
    return (360.0 - abs(proj.arc)) / abs(proj.arc) * proj.n_rows


def assert_no_two_titles_overlap(scene, document) -> list[TextMark]:
    titles = title_marks(scene, document)
    boxes = [text_corners(m) for m in titles]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not overlaps(boxes[i], boxes[j]), (
                f"{titles[i].text!r} overlaps {titles[j].text!r}")
    return titles


def example_document(mode: LayoutMode, *, titles=None, **params) -> Document:
    tree = load_tree(EXAMPLES / "primates.nwk")
    tracks = [load_annotation(EXAMPLES / "primates_region.mytrack", tree),
              load_annotation(EXAMPLES / "primates_bodymass.mytrack", tree)]
    if titles is not None:
        for track, title in zip(tracks, titles):
            track.title = title
    return Document(tree=tree, params=LayoutParams(mode=mode, **params),
                    tracks=tracks)


def strip_stack(mode: LayoutMode, titles, thickness: float = 8.0,
                **params) -> Document:
    """Several deliberately thin colour strips, each with a wide caption."""
    tree = load_tree(EXAMPLES / "primates.nwk")
    tips = [n.name for n in tree.nodes if n.is_tip and n.name]
    tracks = []
    for i, title in enumerate(titles):
        rows = {n.id: [f"g{n.id % 3}"] for n in tree.nodes
                if n.is_tip and n.name in tips}
        tracks.append(ColorStripTrack(
            id=f"strip{i}", title=title,
            data=TrackData(columns=["group"], rows=rows),
            options={"thickness": thickness}))
    return Document(tree=tree, params=LayoutParams(mode=mode, **params),
                    tracks=tracks)


pytestmark = pytest.mark.skipif(not EXAMPLES.exists(),
                                reason="examples/ not present")


# ------------------------------------------------------- the reported defect


@pytest.mark.parametrize("mode", [LayoutMode.RECTANGULAR, LayoutMode.CIRCULAR])
def test_the_two_track_example_draws_one_caption_per_track_without_overlap(mode):
    document = example_document(mode)
    titles = assert_no_two_titles_overlap(compose(document), document)
    assert sorted(m.text for m in titles) == ["Biogeographic region",
                                              "Body mass (kg)"]


def test_a_caption_wider_than_its_strip_is_turned_across_the_band():
    """The 14 unit strip case: along the band there is nowhere to spill but
    sideways, and sideways is the next track's header."""
    document = example_document(LayoutMode.RECTANGULAR)
    scene = compose(document)
    strip = document.tracks[0]
    thickness = float(strip.opt("thickness"))
    width = METRICS.advance(strip.title, Theme().track_title_size,
                            family=Theme().font_family)
    assert width > thickness, "the fixture no longer reproduces the defect"

    caption = next(m for m in title_marks(scene, document)
                   if m.text == strip.title)
    assert abs(caption.rotation) == pytest.approx(90.0)
    xs = [x for x, _ in text_corners(caption)]
    assert max(xs) - min(xs) < thickness, (
        "a turned caption must fit inside the column it belongs to")


@pytest.mark.parametrize("mode", [LayoutMode.RECTANGULAR, LayoutMode.CIRCULAR])
def test_a_caption_never_lands_on_the_next_track_s_axis_labels(mode):
    """The collision as it was actually reported.

    The bar chart writes its value-axis labels at row -0.6, which is the same
    header strip the colour strip's caption was centred in; a caption five
    times wider than its own 18 unit column reached straight into them.
    """
    from makeyourtree.scene.marks import Layer

    document = example_document(mode)
    scene = compose(document)
    titles = title_marks(scene, document)
    assert len(titles) == 2
    ids = {t.id for t in document.tracks}
    stack = list(scene.layers.get(Layer.TRACKS, ()))
    others = []
    while stack:
        mark = stack.pop()
        if isinstance(mark, GroupMark):
            stack.extend(mark.marks)
        elif isinstance(mark, TextMark) and mark.tag not in ids:
            others.append(mark)
    assert others, "the bar chart drew no axis labels; the fixture is wrong"
    for title in titles:
        for other in others:
            assert not overlaps(text_corners(title), text_corners(other)), (
                f"the caption {title.text!r} covers the axis label "
                f"{other.text!r}")


def test_a_caption_that_fits_its_track_is_left_alone():
    """Turning every caption would be a cure worse than the disease."""
    document = example_document(LayoutMode.RECTANGULAR)
    scene = compose(document)
    bars = document.tracks[1]
    caption = next(m for m in title_marks(scene, document) if m.text == bars.title)
    assert caption.rotation == pytest.approx(0.0)


@pytest.mark.parametrize("mode", [LayoutMode.RECTANGULAR, LayoutMode.CIRCULAR])
def test_captions_sit_before_the_first_tip_row(mode):
    """A header row belongs outside the data, not on top of the first tip."""
    document = example_document(mode)
    scene = compose(document)
    frame = scene.metadata["frame"]
    proj = frame.projector
    for mark in title_marks(scene, document):
        for x, y in text_corners(mark):
            if proj.is_polar:
                cx, cy = frame.center
                row = _row_of_angle(proj, math.degrees(math.atan2(y - cy, x - cx)))
            else:
                row = (y - proj.top_y) / proj.row_height
            assert row < 1.0, f"{mark.text!r} reaches into the first tip's row"


def _row_of_angle(proj, degrees: float) -> float:
    span = proj.arc * proj.direction
    if abs(span) < 1e-9 or proj.n_rows <= 0:
        return 0.0
    delta = (degrees - proj.start_angle + 180.0) % 360.0 - 180.0
    return delta / span * proj.n_rows


# ------------------------------------------------------------- long captions


@pytest.mark.parametrize("mode", [LayoutMode.RECTANGULAR, LayoutMode.CIRCULAR])
def test_a_deliberately_very_long_caption_still_cannot_overlap(mode):
    document = example_document(mode, titles=[LONG_TITLE, LONG_TITLE[::-1]])
    scene, sink = composed(document)
    assert_no_two_titles_overlap(scene, document)
    assert_every_track_is_drawn_or_reported(scene, document, sink)
    if mode is LayoutMode.RECTANGULAR:
        assert len(title_marks(scene, document)) == 2, (
            "a rectangular header row has no budget to run out of")


@pytest.mark.parametrize("mode", [LayoutMode.RECTANGULAR, LayoutMode.CIRCULAR])
def test_a_caption_too_long_even_when_turned_is_ellipsised(mode):
    document = example_document(mode, titles=[LONG_TITLE, "Body mass (kg)"])
    scene = compose(document)
    drawn = [m.text for m in title_marks(scene, document)]
    cut = next(t for t in drawn if t != "Body mass (kg)")
    assert cut != LONG_TITLE and LONG_TITLE.startswith(cut.rstrip("…").rstrip())
    assert cut.endswith("…")
    theme = Theme()
    assert METRICS.advance(cut, theme.track_title_size,
                           family=theme.font_family) <= MAX_HEADER_DEPTH


# ------------------------------------------------------- crowded header rows


CROWDED = ["Continental biogeographic region", "Dietary guild assignment",
           "Sampling locality code", "Karyotype grouping",
           "Mitochondrial haplogroup"]


@pytest.mark.parametrize("mode", [LayoutMode.RECTANGULAR, LayoutMode.CIRCULAR])
def test_five_thin_strips_with_wide_captions_are_staggered_not_stacked(mode):
    """Turning is not always enough: five 8 unit columns cannot hold five
    captions side by side, so the packer moves them onto further header rows.

    Beside a rectangular tree every caption is placed, because the page grows
    to hold the header.  A fan cannot grow one: the assertion there is the
    weaker -- and the only honest -- one, that each caption was either placed
    or reported.  Both cases are covered because the packer is shared.
    """
    document = strip_stack(mode, CROWDED)
    scene, sink = composed(document)
    titles = assert_no_two_titles_overlap(scene, document)
    assert_every_track_is_drawn_or_reported(scene, document, sink)

    frame = scene.metadata["frame"]
    proj = frame.projector
    if not proj.is_polar:
        assert len(titles) == len(CROWDED)
        depths = {round(m.y, 3) for m in titles}
        assert len(depths) > 1, "every caption landed on one header row"


# ------------------------------------------------- the header a fan can offer


@pytest.mark.parametrize("arc", [300.0, 330.0, 350.0, 359.0])
def test_no_caption_in_a_fan_leaves_the_gap_the_arc_opens(arc):
    """A fan's header row wraps: row ``-g`` and row ``n_rows - g`` are the same
    place on the page.

    So a caption pushed past the gap is not merely crowding the data, it is
    drawn on top of the LAST tips' tracks.  That is where "Gene presence" ended
    up in the manuscript's Figure 2, lying across the gene columns it names.
    """
    document = strip_stack(LayoutMode.CIRCULAR, CROWDED, arc=arc)
    scene, sink = composed(document)
    frame = scene.metadata["frame"]
    proj = frame.projector
    gap = gap_rows(frame)
    cx, cy = frame.center
    assert_every_track_is_drawn_or_reported(scene, document, sink)
    for mark in title_marks(scene, document):
        for x, y in text_corners(mark):
            row = _row_of_angle(proj, math.degrees(math.atan2(y - cy, x - cx)))
            assert -gap - _EPS <= row <= _EPS, (
                f"{mark.text!r} reaches row {row:.3f} of a {gap:.3f} row gap")


def test_a_closed_fan_has_no_header_row_at_all_and_says_so():
    """A 360 degree fan leaves no wedge, so there is nowhere a caption can go."""
    document = example_document(LayoutMode.CIRCULAR, arc=360.0)
    scene, sink = composed(document)
    assert title_marks(scene, document) == []
    reported = [d for d in sink.items if d.code == NO_ROOM]
    assert len(reported) == 1
    for track in document.tracks:
        assert repr(track.title) in reported[0].message
    assert "legend" in reported[0].message, (
        "the report has to say where the names can still be read")


def test_a_fan_wide_enough_for_its_captions_still_draws_them_all():
    """The budget must not be a licence to drop captions that do fit."""
    document = strip_stack(LayoutMode.CIRCULAR, CROWDED, arc=240.0)
    scene, sink = composed(document)
    assert_no_two_titles_overlap(scene, document)
    assert len(title_marks(scene, document)) == len(CROWDED)
    assert not [d for d in sink.items if d.code == NO_ROOM]


# ----------------------------------------------------------------- options


def test_show_title_false_suppresses_only_that_caption():
    document = example_document(LayoutMode.RECTANGULAR)
    document.tracks[0].options["show_title"] = False
    scene = compose(document)
    assert [m.text for m in title_marks(scene, document)] == ["Body mass (kg)"]


def test_a_track_with_no_bound_rows_gets_no_caption():
    """A caption floating beside a column that drew nothing says nothing."""
    document = example_document(LayoutMode.RECTANGULAR)
    document.tracks[0].data.rows.clear()
    scene = compose(document)
    assert [m.text for m in title_marks(scene, document)] == ["Body mass (kg)"]


def test_a_track_no_longer_captions_itself_inside_the_compositor():
    """Two captions for one track would overlap by construction.

    The colour strip still draws its own caption when it is drawn on its own --
    there is no stack to collide with then -- so the check is that the
    compositor produces exactly one mark per track, not that the track code is
    gone.
    """
    document = example_document(LayoutMode.RECTANGULAR)
    scene = compose(document)
    drawn = [m.text for m in title_marks(scene, document)]
    assert len(drawn) == len(set(drawn)) == len(document.tracks)

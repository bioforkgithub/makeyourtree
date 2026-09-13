# SPDX-License-Identifier: MIT
"""The compositor: batching, tagging, page sizing and every layout mode."""
from __future__ import annotations

import math
import time

import pytest

from makeyourtree.layout.params import BranchMode, CollapseShape, LayoutMode
from makeyourtree.render.svg import render_svg
from makeyourtree.scene.compose import compose
from makeyourtree.scene.marks import (GroupMark, Layer, LinesMark, Mark, PathMark,
                                  PolygonMark, RectMark, TextMark)
from makeyourtree.doc.document import Document
from makeyourtree.layout.params import LayoutParams
from makeyourtree.style.color import Color
from makeyourtree.style.theme import DARK, Theme, resolve
from makeyourtree.tracks.base import TrackData
from makeyourtree.tracks.strip import ColorStripTrack

from _render_support import build_tree, caterpillar, geometric_bounds, make_document, parse_svg

ALL_MODES = list(LayoutMode)


def marks_in(scene, layer: Layer) -> list[Mark]:
    """Every mark in one layer, with the compositor's translation group unwrapped."""
    out: list[Mark] = []
    stack = list(scene.layers.get(layer, ()))
    while stack:
        mark = stack.pop()
        if isinstance(mark, GroupMark):
            stack.extend(mark.marks)
        else:
            out.append(mark)
    return out


# ------------------------------------------------------------------- modes


@pytest.mark.parametrize("mode", ALL_MODES, ids=[m.value for m in ALL_MODES])
def test_every_layout_mode_composes_and_renders(mode):
    scene = compose(make_document(mode=mode))
    assert scene.width > 0 and scene.height > 0
    assert marks_in(scene, Layer.BRANCHES), "no branches were emitted"
    labels = [m for m in marks_in(scene, Layer.LABELS) if isinstance(m, TextMark)]
    assert {m.text for m in labels} >= {"Betavirus", "Gammaphage"}
    parse_svg(render_svg(scene))


@pytest.mark.parametrize("branch_mode", list(BranchMode),
                         ids=[b.value for b in BranchMode])
def test_every_branch_mode_composes(branch_mode):
    scene = compose(make_document(branch_mode=branch_mode))
    assert marks_in(scene, Layer.BRANCHES)
    parse_svg(render_svg(scene))


def test_polar_modes_emit_arc_connectors():
    scene = compose(make_document(mode=LayoutMode.CIRCULAR))
    arcs = [m for m in marks_in(scene, Layer.BRANCHES) if isinstance(m, PathMark)]
    assert arcs, "a circular layout must join siblings with arcs"
    assert any(seg[0] == "A" for m in arcs for seg in m.segments)


def test_rectangular_mode_draws_elbows_not_diagonals():
    scene = compose(make_document(mode=LayoutMode.RECTANGULAR))
    lines = [m for m in marks_in(scene, Layer.BRANCHES) if isinstance(m, LinesMark)]
    coords = [c for m in lines for c in m.coords]
    for i in range(0, len(coords), 4):
        x0, y0, x1, y1 = coords[i:i + 4]
        assert math.isclose(x0, x1, abs_tol=1e-6) or math.isclose(y0, y1, abs_tol=1e-6)


def test_slanted_mode_draws_one_diagonal_per_edge():
    tree = build_tree()
    scene = compose(make_document(tree, mode=LayoutMode.SLANTED))
    lines = [m for m in marks_in(scene, Layer.BRANCHES) if isinstance(m, LinesMark)]
    total = sum(m.count for m in lines)
    assert total == len(tree.nodes) - 1


# ---------------------------------------------------------------- batching


def test_branches_are_batched_by_paint_not_by_node():
    tree = caterpillar(4000)
    scene = compose(make_document(tree))
    branch_marks = marks_in(scene, Layer.BRANCHES)
    assert len(branch_marks) == 1
    assert sum(m.count for m in branch_marks) > 4000


def test_large_tree_stays_far_below_one_mark_per_node():
    tree = caterpillar(20000)
    started = time.perf_counter()
    scene = compose(make_document(tree, show_tip_labels=False))
    elapsed = time.perf_counter() - started
    assert len(tree.nodes) > 20000
    assert scene.count() < 20, (
        f"{scene.count()} marks for {len(tree.nodes)} nodes: batching is broken")
    assert elapsed < 60.0


def test_mark_count_tracks_distinct_paints():
    tree = build_tree()
    scene = compose(make_document(tree))
    plain = len([m for m in marks_in(scene, Layer.BRANCHES)
                 if isinstance(m, LinesMark)])
    assert plain == 1

    tree.by_name("clade_left").set_style(branch_color=Color(200, 0, 0))
    tree.by_name("Gammaphage").set_style(branch_color=Color(0, 120, 0))
    scene = compose(make_document(tree))
    buckets = [m for m in marks_in(scene, Layer.BRANCHES)
               if isinstance(m, LinesMark)]
    assert len(buckets) == 3
    strokes = {m.paint.stroke for m in buckets}
    assert strokes == {Theme().branch_color, Color(200, 0, 0), Color(0, 120, 0)}


def test_batched_paint_matches_the_frozen_resolve():
    """The fast inherited-style walk must agree with ``style.theme.resolve``."""
    tree = build_tree()
    tree.by_name("clade_left").set_style(branch_color=Color(11, 22, 33),
                                         branch_width=3.0)
    scene = compose(make_document(tree))
    child = tree.by_name("Betavirus")
    expected = resolve(child, Theme())
    buckets = {(m.paint.stroke, m.paint.width)
               for m in marks_in(scene, Layer.BRANCHES)
               if isinstance(m, LinesMark)}
    assert (expected["branch_color"], expected["branch_width"]) in buckets
    assert (Color(11, 22, 33), 3.0) in buckets


def test_dashed_branch_style_makes_its_own_bucket():
    tree = build_tree()
    tree.by_name("clade_right").set_style(branch_dash=(3.0, 2.0))
    scene = compose(make_document(tree))
    dashes = {m.paint.dash for m in marks_in(scene, Layer.BRANCHES)
              if isinstance(m, LinesMark)}
    assert dashes == {None, (3.0, 2.0)}


# ----------------------------------------------------------------- tagging


def test_tip_labels_carry_their_node_id():
    tree = build_tree()
    scene = compose(make_document(tree))
    tagged = {m.text: m.tag for m in marks_in(scene, Layer.LABELS)
              if isinstance(m, TextMark)}
    for name, tag in tagged.items():
        node = tree.by_id(tag)
        assert node is not None and node.name == name


def test_collapsed_glyph_carries_its_node_id():
    tree = build_tree()
    node = tree.by_name("clade_left")
    node.collapsed = True
    tree.touch()
    tree.refresh()
    scene = compose(make_document(tree))
    glyphs = marks_in(scene, Layer.COLLAPSED)
    assert glyphs, "a collapsed clade must produce a glyph"
    assert all(g.tag == node.id for g in glyphs)


@pytest.mark.parametrize("shape", list(CollapseShape))
def test_collapse_shapes_all_render(shape):
    tree = build_tree()
    tree.by_name("clade_right").collapsed = True
    tree.touch()
    tree.refresh()
    scene = compose(make_document(tree, collapse_shape=shape))
    glyphs = marks_in(scene, Layer.COLLAPSED)
    assert len(glyphs) == 1
    if shape is CollapseShape.BAR:
        assert isinstance(glyphs[0], RectMark)
    else:
        assert isinstance(glyphs[0], PolygonMark)
    parse_svg(render_svg(scene))


def test_collapsed_clade_hides_its_descendants():
    tree = build_tree()
    tree.by_name("clade_left").collapsed = True
    tree.touch()
    tree.refresh()
    scene = compose(make_document(tree))
    texts = {m.text for m in marks_in(scene, Layer.LABELS)
             if isinstance(m, TextMark)}
    assert "Betavirus" not in texts
    assert "Gammaphage" in texts


# ------------------------------------------------------------------ labels


def test_max_label_width_ellipsises_through_the_metrics():
    scene = compose(make_document(max_label_width=30.0))
    texts = [m.text for m in marks_in(scene, Layer.LABELS)
             if isinstance(m, TextMark)]
    assert any(t.endswith("…") for t in texts)
    assert "Alphaproteobacteria sp." not in texts


def test_tip_labels_can_be_turned_off():
    scene = compose(make_document(show_tip_labels=False))
    assert [m for m in marks_in(scene, Layer.LABELS)
            if isinstance(m, TextMark)] == []


def test_internal_labels_are_opt_in():
    without = compose(make_document())
    with_them = compose(make_document(show_internal_labels=True))
    names_off = {m.text for m in marks_in(without, Layer.LABELS)
                 if isinstance(m, TextMark)}
    names_on = {m.text for m in marks_in(with_them, Layer.LABELS)
                if isinstance(m, TextMark)}
    assert "clade_left" not in names_off
    assert {"clade_left", "clade_right", "root"} <= names_on


def test_node_label_overrides_beat_the_tree_name():
    tree = build_tree()
    tree.by_name("Betavirus").set_style(label_text="renamed",
                                        label_color=Color(9, 9, 9),
                                        label_bold=True)
    tree.by_name("Gammaphage").set_style(label_hidden=True)
    scene = compose(make_document(tree))
    labels = {m.text: m for m in marks_in(scene, Layer.LABELS)
              if isinstance(m, TextMark)}
    assert "renamed" in labels and "Betavirus" not in labels
    assert labels["renamed"].style.color == Color(9, 9, 9)
    assert labels["renamed"].style.weight >= 600
    assert "Gammaphage" not in labels


def test_polar_labels_are_rotated_to_follow_the_radius():
    scene = compose(make_document(mode=LayoutMode.CIRCULAR, rotate_labels=True))
    rotations = {round(m.rotation, 3) for m in marks_in(scene, Layer.LABELS)
                 if isinstance(m, TextMark)}
    assert rotations != {0.0}

    upright = compose(make_document(mode=LayoutMode.CIRCULAR,
                                    rotate_labels=False))
    assert {m.rotation for m in marks_in(upright, Layer.LABELS)
            if isinstance(m, TextMark)} == {0.0}


# --------------------------------------------------------- decor and guides


def test_aligned_tips_draw_guide_lines():
    without = compose(make_document(align_tips=False))
    assert marks_in(without, Layer.GRID) == []
    scene = compose(make_document(align_tips=True, guide_lines=True))
    guides = [m for m in marks_in(scene, Layer.GRID) if isinstance(m, LinesMark)]
    assert len(guides) == 1, "leaders must be one batched mark, not one per tip"
    coords = guides[0].coords
    columns = {round(coords[i + 2], 6) for i in range(0, len(coords), 4)}
    assert len(columns) == 1, "every leader must end at the same label column"
    column = columns.pop()
    frame = scene.metadata["frame"]
    # A tip already sitting at the column has no gap to bridge and gets none.
    expected = sum(1 for tip in frame.tips if frame.x(tip) < column - 0.5)
    assert expected >= 1
    assert guides[0].count == expected
    assert guides[0].paint.dash == Theme().guide_dash


def test_guide_lines_can_be_suppressed():
    scene = compose(make_document(align_tips=True, guide_lines=False))
    assert marks_in(scene, Layer.GRID) == []


def test_scale_bar_is_a_round_number_of_branch_length_units():
    scene = compose(make_document())
    units, length = scene.metadata["scalebar"]
    mantissa = units / 10.0 ** math.floor(math.log10(units))
    assert mantissa == pytest.approx(round(mantissa), abs=1e-9)
    assert int(round(mantissa)) in (1, 2, 5)
    labels = [m.text for m in marks_in(scene, Layer.DECOR)
              if isinstance(m, TextMark)]
    assert f"{units:g}" in labels


def test_scale_bar_is_absent_for_a_cladogram():
    scene = compose(make_document(branch_mode=BranchMode.CLADOGRAM_ALIGNED))
    assert "scalebar" not in scene.metadata


def test_a_fan_puts_its_scale_bar_outside_the_rings():
    """``body_bounds`` is the SQUARE around a fan, so the anchor the layout
    suggests -- its bottom-left corner -- is at 1.41 times the body radius.

    That is not beside the drawing, it is inside it: in the annulus the tip
    labels occupy, which is where the manuscript's Figure 2 had the bar, lying
    across three tip names.  A fan has no empty corner, so the compositor moves
    the bar below everything it has already drawn.
    """
    tree = build_tree()
    rows = {n.id: ["a" if n.id % 2 else "b"] for n in tree.nodes if n.is_tip}
    # The ring is deliberately deep: the corner sits at 1.41 body radii, so a
    # thin stack would leave it outside by luck and the assertion would pass
    # against the defect it was written for.
    strip = ColorStripTrack(id="strip", title="Group",
                            data=TrackData(columns=["group"], rows=rows),
                            options={"thickness": 400.0})
    document = Document(tree=tree, theme=Theme(),
                        params=LayoutParams(mode=LayoutMode.CIRCULAR),
                        tracks=[strip])
    scene = compose(document)
    frame = scene.metadata["frame"]
    cx, cy = frame.center
    outer = (frame.projector.base_r
             + max(scene.metadata["track_offsets"].values()) + 400.0)

    bar = next(m for m in marks_in(scene, Layer.DECOR)
               if isinstance(m, LinesMark))
    for x, y in zip(bar.coords[0::2], bar.coords[1::2]):
        assert math.hypot(x - cx, y - cy) > outer, (
            "the bar is drawn on top of the rings")
    for label in (m for m in marks_in(scene, Layer.LABELS)
                  if isinstance(m, TextMark)):
        assert math.hypot(label.x - cx, label.y - cy) < outer


def test_axis_grid_is_opt_in():
    theme = Theme(axis_show=True)
    off = compose(make_document())
    on = compose(make_document(theme=theme))
    assert marks_in(off, Layer.GRID) == []
    assert any(isinstance(m, LinesMark) for m in marks_in(on, Layer.GRID))


def test_polar_axis_uses_rings():
    theme = Theme(axis_show=True)
    scene = compose(make_document(theme=theme, mode=LayoutMode.CIRCULAR))
    rings = [m for m in marks_in(scene, Layer.GRID) if isinstance(m, PathMark)]
    assert rings
    assert any(seg[0] == "A" for seg in rings[0].segments)
    parse_svg(render_svg(scene))


def test_support_values_honour_threshold_format_and_position():
    theme = Theme(show_support=True, support_format="{:.0f}%", support_min=70.0)
    scene = compose(make_document(theme=theme))
    texts = [m for m in marks_in(scene, Layer.DECOR) if isinstance(m, TextMark)]
    values = {m.text for m in texts}
    assert "88%" in values
    assert "61%" not in values, "support below support_min must be dropped"

    above = {m.text: m.y for m in texts if m.text == "88%"}
    below_theme = Theme(show_support=True, support_format="{:.0f}%",
                        support_position="below")
    below = {m.text: m.y for m in marks_in(compose(make_document(theme=below_theme)),
                                           Layer.DECOR)
             if isinstance(m, TextMark) and m.text == "88%"}
    assert below["88%"] > above["88%"]


def test_support_position_node_draws_a_marker_instead_of_text():
    from makeyourtree.scene.marks import EllipseMark
    theme = Theme(show_support=True, support_position="node")
    scene = compose(make_document(theme=theme))
    decor = marks_in(scene, Layer.DECOR)
    assert any(isinstance(m, EllipseMark) for m in decor)
    assert not any(isinstance(m, TextMark) and m.text.startswith("8")
                   for m in decor)


def test_clade_fill_paints_an_underlay_band():
    tree = build_tree()
    tree.by_name("clade_left").set_style(clade_fill=Color(255, 230, 200))
    scene = compose(make_document(tree))
    under = marks_in(scene, Layer.UNDERLAY)
    assert under
    fills = [c for m in under for c in (m.fills or ())]
    assert Color(255, 230, 200) in fills


# ------------------------------------------------------------------ sizing


@pytest.mark.parametrize("mode", ALL_MODES, ids=[m.value for m in ALL_MODES])
def test_page_covers_every_drawn_mark(mode):
    scene = compose(make_document(mode=mode))
    x0, y0, x1, y1 = geometric_bounds(scene)
    assert x0 >= -1e-6 and y0 >= -1e-6
    assert x1 <= scene.width + 1e-6
    assert y1 <= scene.height + 1e-6


def test_page_widens_for_a_long_tip_label():
    short = compose(make_document())
    tree = build_tree()
    tree.by_name("Betavirus").name = "B" * 400
    tree.reindex()
    long_label = compose(make_document(tree))
    assert long_label.width > short.width + 100


def test_requested_size_is_a_floor_never_a_crop():
    natural = compose(make_document())
    padded = compose(make_document(), size=(natural.width + 500,
                                            natural.height + 400))
    assert padded.width == pytest.approx(natural.width + 500)
    assert padded.height == pytest.approx(natural.height + 400)

    squeezed = compose(make_document(), size=(10.0, 10.0))
    assert squeezed.width == pytest.approx(natural.width)
    assert squeezed.height == pytest.approx(natural.height)


def test_content_overhanging_the_origin_is_shifted_in_not_clipped():
    scene = compose(make_document(mode=LayoutMode.UNROOTED))
    dx, dy = scene.metadata["origin"]
    assert dx >= 0 and dy >= 0
    x0, y0, _, _ = geometric_bounds(scene)
    assert x0 >= -1e-6 and y0 >= -1e-6


def test_background_comes_from_the_theme():
    assert compose(make_document()).background == Theme().background
    assert compose(make_document(theme=DARK)).background == DARK.background


def test_scene_metadata_exposes_the_frame_for_hit_testing():
    scene = compose(make_document())
    frame = scene.metadata["frame"]
    assert frame.tips
    assert scene.metadata["content_bounds"][2] > 0

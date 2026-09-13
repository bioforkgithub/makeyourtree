# SPDX-License-Identifier: MIT
"""Aligned tips in a fan, and the radial leaders that bridge the gap.

``align_tips`` worked in the linear family and was silently ignored in the
polar one: the labels moved to the ring, the tips stayed where their branch
lengths put them, and the polar pass published no ``metadata["guides"]`` at
all, so nothing downstream could tell that a gap existed.  These tests pin the
fixed behaviour to the contract the linear pass already had -- the same flat
quadruple form, the same start rule and the same minimum length -- because the
compositor consumes both families through one code path.
"""

from __future__ import annotations

import math

import pytest

from makeyourtree.core.node import Node
from makeyourtree.layout import compute_layout
from makeyourtree.layout.collapse import depth_stats
from makeyourtree.layout.linear import MIN_GUIDE_LENGTH
from makeyourtree.layout.params import LayoutMode, LayoutParams
from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics

from _polar_support import make_tree, named

METRICS = CachedMetrics(FallbackMetrics())


def ragged():
    """Four tips at four different depths, so every leader is a different length."""
    return make_tree(named(None, None,
                           named(None, 0.2, Node("A", 0.1), Node("B", 0.5)),
                           named(None, 0.4, Node("C", 0.3), Node("D", 1.1))))


def lay(tree, mode=LayoutMode.CIRCULAR, **kw):
    return compute_layout(tree, LayoutParams(mode=mode, align_tips=True,
                                             guide_lines=True, **kw), METRICS)


def quads(frame):
    guides = frame.metadata["guides"]
    assert len(guides) % 4 == 0, "guides are flat x0, y0, x1, y1 quadruples"
    return [tuple(guides[i:i + 4]) for i in range(0, len(guides), 4)]


def polar_of(frame, x, y):
    """``(radius, angle)`` of a scene point about the fan's centre."""
    cx, cy = frame.center
    return (math.hypot(x - cx, y - cy),
            math.degrees(math.atan2(y - cy, x - cx)))


def normalised(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


def needs_a_leader(frame, tip: int, gap: float) -> bool:
    outer = frame.metadata["outer_radius"]
    return outer - (frame.radius(tip) + gap) > MIN_GUIDE_LENGTH


# ------------------------------------------------------------ the guides exist


def test_a_fan_publishes_a_leader_for_every_tip_that_has_a_gap_to_bridge():
    """The reported defect: rectangular listed leaders, circular listed none.

    In a fan phylogram the deepest tip defines the ring, so it is always
    already on it and has nothing to bridge -- exactly the case
    :meth:`makeyourtree.layout.linear.LinearLayout._guides` drops.  Every other
    visible tip gets one leader, and no tip gets two.
    """
    frame = lay(ragged(), tip_label_gap=0.0)
    needy = [t for t in frame.tips if needs_a_leader(frame, t, 0.0)]
    assert len(needy) == len(frame.tips) - 1, "the fixture must be ragged"
    assert len(quads(frame)) == len(needy)

    by_angle = {round(normalised(polar_of(frame, q[0], q[1])[1]), 6)
                for q in quads(frame)}
    assert by_angle == {round(normalised(frame.angle(t)), 6) for t in needy}


def test_the_tip_without_a_leader_is_the_one_already_on_the_ring():
    frame = lay(ragged(), tip_label_gap=0.0)
    outer = frame.metadata["outer_radius"]
    served = {round(normalised(polar_of(frame, q[0], q[1])[1]), 6)
              for q in quads(frame)}
    missing = [t for t in frame.tips
               if round(normalised(frame.angle(t)), 6) not in served]
    assert len(missing) == 1
    assert frame.radius(missing[0]) == pytest.approx(outer)


def test_no_guides_are_produced_when_tips_are_not_aligned():
    frame = compute_layout(ragged(),
                           LayoutParams(mode=LayoutMode.CIRCULAR,
                                        guide_lines=True), METRICS)
    assert "guides" not in frame.metadata


def test_guides_can_be_switched_off_while_tips_stay_aligned():
    frame = compute_layout(ragged(),
                           LayoutParams(mode=LayoutMode.CIRCULAR,
                                        align_tips=True, guide_lines=False),
                           METRICS)
    assert "guides" not in frame.metadata


# ---------------------------------------------------------------- the geometry


def test_each_guide_runs_radially_from_its_own_tip_to_the_ring():
    frame = lay(ragged(), tip_label_gap=0.0)
    outer = frame.metadata["outer_radius"]
    needy = [t for t in frame.tips if needs_a_leader(frame, t, 0.0)]
    assert len(quads(frame)) == len(needy)
    for tip, (x0, y0, x1, y1) in zip(needy, quads(frame)):
        r0, a0 = polar_of(frame, x0, y0)
        r1, a1 = polar_of(frame, x1, y1)
        assert r0 == pytest.approx(frame.radius(tip))
        assert r1 == pytest.approx(outer)
        # Radial means ONE angle, not two: a leader that drifted round the ring
        # would cross the neighbouring tip's own branch.
        assert a0 == pytest.approx(a1, abs=1e-9)
        assert a1 == pytest.approx(normalised(frame.angle(tip)), abs=1e-9)


def test_a_guide_starts_past_its_tip_by_the_label_gap():
    frame = lay(ragged(), tip_label_gap=9.0)
    needy = [t for t in frame.tips if needs_a_leader(frame, t, 9.0)]
    for tip, (x0, y0, _x1, _y1) in zip(needy, quads(frame)):
        assert polar_of(frame, x0, y0)[0] == pytest.approx(frame.radius(tip) + 9.0)


def test_every_guide_is_longer_than_the_minimum_readable_run():
    """A two-unit stub reads as a smudge, not as a leader."""
    frame = lay(ragged(), tip_label_gap=0.0)
    for x0, y0, x1, y1 in quads(frame):
        r0, _ = polar_of(frame, x0, y0)
        r1, _ = polar_of(frame, x1, y1)
        assert r1 - r0 > MIN_GUIDE_LENGTH


def test_aligning_tips_does_not_move_them():
    """A leader is a reading aid drawn in the gap, not a lie about depth.

    The linear pass makes exactly this promise; a fan that quietly pushed its
    tips out to the ring would draw every branch at the wrong length while
    still calling itself a phylogram.
    """
    tree = ragged()
    plain = compute_layout(tree, LayoutParams(mode=LayoutMode.CIRCULAR), METRICS)
    aligned = lay(tree)
    assert ([aligned.radius(t) for t in aligned.tips]
            == [plain.radius(t) for t in plain.tips])


def test_a_radial_cladogram_needs_no_leaders_because_its_tips_are_the_ring():
    frame = lay(ragged(), mode=LayoutMode.RADIAL)
    assert frame.metadata["guides"] == []


def test_a_collapsed_clade_is_not_overdrawn_by_its_own_guide():
    """The leader starts past the summary glyph, as it does in a linear frame."""
    tree = ragged()
    clade = tree.root.children[0]
    clade.collapsed = True
    tree.refresh()
    frame = lay(tree, tip_label_gap=0.0)
    overhang = max(0.0, depth_stats(clade)[1] - clade.depth_len)
    glyph_far = frame.radius(clade.id) + overhang * frame.scale
    assert overhang > 0.0, "the collapsed clade must actually reach past its node"

    angle = round(normalised(frame.angle(clade.id)), 6)
    starts = {round(normalised(polar_of(frame, q[0], q[1])[1]), 6):
              polar_of(frame, q[0], q[1])[0] for q in quads(frame)}
    assert starts[angle] == pytest.approx(glyph_far)


# ---------------------------------------------------------- compositor contract


def test_the_compositor_draws_exactly_the_leaders_the_layout_published():
    from makeyourtree.doc.document import Document
    from makeyourtree.scene.compose import compose
    from makeyourtree.scene.marks import GroupMark, Layer, LinesMark

    document = Document(tree=ragged(),
                        params=LayoutParams(mode=LayoutMode.CIRCULAR,
                                            align_tips=True, guide_lines=True))
    scene = compose(document)
    marks = list(scene.layers.get(Layer.GRID, ()))
    while marks and isinstance(marks[0], GroupMark):
        marks = list(marks[0].marks)
    lines = [m for m in marks if isinstance(m, LinesMark)]
    assert len(lines) == 1, "leaders must be one batched mark, not one per tip"
    published = scene.metadata["frame"].metadata["guides"]
    assert published, "the fan published no leaders to draw"
    assert list(lines[0].coords) == pytest.approx(list(published))

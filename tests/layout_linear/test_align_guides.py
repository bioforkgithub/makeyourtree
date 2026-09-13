# SPDX-License-Identifier: MIT
"""Aligned tips and the dotted guide geometry they need."""
from __future__ import annotations

import pytest

from makeyourtree.layout.linear import MIN_GUIDE_LENGTH, LinearLayout
from makeyourtree.layout.params import LayoutParams

from .conftest import C, L, build


def lay(tree, metrics, **kw):
    return LinearLayout().compute(tree, LayoutParams(**kw), metrics)


@pytest.fixture
def ragged():
    return build(C(L("A", 0.2), L("B", 0.6), L("C", 1.0)))


def test_no_guides_unless_tips_are_aligned(ragged, metrics):
    assert "guides" not in lay(ragged, metrics).metadata


def test_guides_run_from_each_tip_to_the_label_column(ragged, metrics):
    frame = lay(ragged, metrics, align_tips=True)
    guides = frame.metadata["guides"]
    assert len(guides) % 4 == 0
    x_align = frame.metadata["align_x"]
    rows = []
    for i in range(0, len(guides), 4):
        x0, y0, x1, y1 = guides[i:i + 4]
        assert y0 == y1
        assert x1 == pytest.approx(x_align)
        assert x1 - x0 > MIN_GUIDE_LENGTH
        rows.append(y0)
    # The deepest tip already sits at the column, so it gets no guide.
    assert rows == [frame.y(t) for t in frame.tips[:2]]


def test_guides_start_past_the_tip_by_the_label_gap(ragged, metrics):
    frame = lay(ragged, metrics, align_tips=True, tip_label_gap=9.0)
    guides = frame.metadata["guides"]
    a = ragged.by_name("A")
    assert guides[0] == pytest.approx(frame.x(a.id) + 9.0)


def test_guides_can_be_switched_off_while_tips_stay_aligned(ragged, metrics):
    frame = lay(ragged, metrics, align_tips=True, guide_lines=False)
    assert "guides" not in frame.metadata


def test_aligning_tips_does_not_move_them(ragged, metrics):
    """Alignment is a reading aid drawn in the gap, not a lie about depth:
    the tip keeps the x its branch length earned."""
    plain = lay(ragged, metrics)
    aligned = lay(ragged, metrics, align_tips=True)
    assert [aligned.x(t) for t in aligned.tips] == [plain.x(t) for t in plain.tips]


def test_a_collapsed_glyph_is_not_overdrawn_by_its_guide(metrics):
    tree = build(C(
        C(L("A", 0.4), L("B", 0.9), bl=0.1, name="clade"),
        L("D", 1.5),
    ))
    tree.by_name("clade").collapsed = True
    frame = lay(tree, metrics, align_tips=True)
    guides = frame.metadata["guides"]
    clade = tree.by_name("clade")
    glyph_far = frame.x(clade.id) + 0.9 * frame.scale
    assert guides[0] == pytest.approx(glyph_far + 6.0)

# SPDX-License-Identifier: MIT
"""Label measurement, the tip offset and the aligned-tip guides."""
from __future__ import annotations

import pytest

from makeyourtree.layout.linear import MEASURE_ALL_BELOW, MEASURE_TOP_K, LinearLayout
from makeyourtree.layout.params import LayoutParams
from makeyourtree.layout.projector import LinearProjector

from .conftest import C, L, build, caterpillar


def lay(tree, metrics, **kw):
    return LinearLayout().compute(tree, LayoutParams(**kw), metrics)


@pytest.fixture
def named():
    return build(C(L("a", 0.5), L("Methanocaldococcus jannaschii", 0.5), L("bb", 0.5)))


def test_every_tip_label_is_measured_and_cached(named, metrics):
    frame = lay(named, metrics)
    assert set(frame.label_widths) == {t for t in frame.tips}
    a = named.by_name("a")
    assert frame.label_widths[a.id] == pytest.approx(
        metrics.advance("a", frame.metadata["label_size"]))


def test_tip_offset_clears_the_widest_label(named, metrics):
    frame = lay(named, metrics, tip_label_gap=6.0)
    widest = max(frame.label_widths.values())
    assert widest == frame.metadata["max_label_width"]
    assert frame.tip_offset == pytest.approx(6.0 + widest)


def test_max_label_width_caps_the_reservation(named, metrics):
    frame = lay(named, metrics, max_label_width=20.0)
    assert max(frame.label_widths.values()) == 20.0
    assert frame.tip_offset == pytest.approx(6.0 + 20.0)


def test_labels_off_reserves_only_the_gap(named, metrics):
    frame = lay(named, metrics, show_tip_labels=False)
    assert frame.label_widths == {}
    assert frame.tip_offset == pytest.approx(6.0)


def test_label_size_comes_through_the_params_escape_hatch(named, metrics):
    small = lay(named, metrics, extra={"label_size": 8.0})
    big = lay(named, metrics, extra={"label_size": 24.0})
    assert big.tip_offset > small.tip_offset
    assert small.metadata["label_size"] == 8.0


def test_large_trees_measure_only_the_longest_candidates(metrics):
    tree = caterpillar(MEASURE_ALL_BELOW + 500)
    frame = lay(tree, metrics)
    assert len(frame.tips) > MEASURE_ALL_BELOW
    assert len(frame.label_widths) == MEASURE_TOP_K
    # The sample must still find the true maximum: the longest names win the
    # character-count race, and in this font no shorter name outruns them.
    longest = max((n.name for n in tree.nodes if n.name), key=len)
    assert frame.metadata["max_label_width"] == pytest.approx(
        metrics.advance(longest, 11.0))


def test_the_projector_puts_offset_zero_at_the_tip_column(named, metrics):
    frame = lay(named, metrics)
    proj = frame.projector
    assert isinstance(proj, LinearProjector)
    assert proj.base_x == pytest.approx(frame.metadata["align_x"])
    assert proj.n_rows == frame.n_rows
    assert proj.row_height == frame.row_height
    for tip in frame.tips:
        _, y = proj.point(frame.row(tip), 0.0)
        assert y == pytest.approx(frame.y(tip))


def test_track_baseline_sits_past_every_label(named, metrics):
    frame = lay(named, metrics)
    x_start, _ = frame.projector.point(0.5, frame.tip_offset)
    for tip in frame.tips:
        label_end = frame.x(tip) + 6.0 + frame.label_widths[tip]
        assert x_start >= label_end - 1e-9

# SPDX-License-Identifier: MIT
"""Edge geometry written into the frame's flat segment array."""
from __future__ import annotations

import pytest

from makeyourtree.layout.linear import LinearLayout
from makeyourtree.layout.params import LayoutMode, LayoutParams

from .conftest import C, L, balanced, build


def lay(tree, metrics, mode=LayoutMode.RECTANGULAR, **kw):
    return LinearLayout().compute(tree, LayoutParams(mode=mode, **kw), metrics)


def segments(frame):
    flat = frame.straight
    return [tuple(flat[i:i + 4]) for i in range(0, len(flat), 4)]


def test_rectangular_emits_one_connector_plus_one_arm_per_child(three_tips, metrics):
    frame = lay(three_tips, metrics)
    segs = segments(frame)
    assert len(segs) == 4
    root = three_tips.root
    rx = frame.x(root.id)
    first, last = frame.tips[0], frame.tips[-1]
    assert segs[0] == (rx, frame.y(first), rx, frame.y(last))
    for seg, tip in zip(segs[1:], frame.tips):
        assert seg == (rx, frame.y(tip), frame.x(tip), frame.y(tip))


def test_rectangular_arms_are_horizontal_and_connectors_vertical(metrics):
    tree = balanced(3)
    frame = lay(tree, metrics)
    for x0, y0, x1, y1 in segments(frame):
        assert x0 == pytest.approx(x1) or y0 == pytest.approx(y1)


def test_rectangular_segment_count_is_one_plus_k_per_internal_node(metrics):
    tree = balanced(4)
    frame = lay(tree, metrics)
    internal = [n for n in tree.nodes if n.children]
    expected = sum(1 + len(n.children) for n in internal)
    assert frame.n_segments == expected


def test_slanted_emits_exactly_one_segment_per_edge(metrics):
    tree = balanced(4)
    frame = lay(tree, metrics, mode=LayoutMode.SLANTED)
    n_edges = sum(len(n.children) for n in tree.nodes)
    assert frame.n_segments == n_edges


def test_slanted_segments_run_corner_to_corner(three_tips, metrics):
    frame = lay(three_tips, metrics, mode=LayoutMode.SLANTED)
    root = three_tips.root
    rx, ry = frame.xy(root.id)
    assert segments(frame) == [(rx, ry, frame.x(t), frame.y(t)) for t in frame.tips]


def test_the_connector_is_emitted_even_when_degenerate(metrics):
    """A node with one visible child still needs its connector: hit-testing
    and the elbow's corner both depend on it existing."""
    tree = build(C(C(L("A", 0.5), name="stem"), L("B", 1.0)))
    frame = lay(tree, metrics)
    stem = tree.by_name("stem")
    sx = frame.x(stem.id)
    y = frame.y(tree.by_name("A").id)
    assert (sx, y, sx, y) in segments(frame)


def test_zero_length_edges_still_produce_a_segment(metrics):
    tree = build(C(L("A", 0.0), L("B", 1.0)))
    frame = lay(tree, metrics)
    a = tree.by_name("A")
    assert (frame.x(tree.root.id), frame.y(a.id),
            frame.x(a.id), frame.y(a.id)) in segments(frame)


def test_hidden_edges_are_not_drawn(metrics):
    tree = build(C(L("A"), C(L("B"), L("C"), name="gone"), L("D")))
    tree.by_name("gone").hidden = True
    frame = lay(tree, metrics)
    assert frame.n_segments == 3

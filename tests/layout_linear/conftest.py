# SPDX-License-Identifier: MIT
"""Synthetic trees for the linear-layout suite.

Trees are built from nested tuples rather than parsed from Newick so that this
suite has no dependency on the io package and so that every branch length in a
fixture is visible at the assertion site.
"""
from __future__ import annotations

import pytest

from makeyourtree.core.node import Node
from makeyourtree.core.tree import Tree


def L(name: str, bl: float | None = 1.0) -> tuple:
    """A leaf spec."""
    return ("leaf", name, bl)


def C(*children: tuple, bl: float | None = 1.0, name: str | None = None) -> tuple:
    """A clade spec."""
    return ("clade", children, bl, name)


def build(spec: tuple, *, rooted: bool = True) -> Tree:
    """Materialise a nested spec into a refreshed :class:`Tree`."""
    tree = Tree(rooted=rooted)
    stack: list[tuple[Node, tuple]] = [(tree.root, spec)]
    while stack:
        node, s = stack.pop()
        if s[0] == "leaf":
            node.name = s[1]
            node.branch_length = s[2]
            continue
        node.branch_length = s[2]
        node.name = s[3]
        for child_spec in s[1]:
            child = tree.new_node()
            node.add_child(child)
            stack.append((child, child_spec))
    tree.root.branch_length = None
    tree.refresh()
    return tree


def caterpillar(n_leaves: int, bl: float = 0.1) -> Tree:
    """A pectinate tree: the shape that breaks recursive layouts."""
    tree = Tree()
    cur = tree.root
    for i in range(n_leaves - 1):
        leaf = tree.new_node(f"t{i}", bl)
        inner = tree.new_node(None, bl)
        cur.add_child(leaf)
        cur.add_child(inner)
        cur = inner
    cur.name = f"t{n_leaves - 1}"
    tree.refresh()
    return tree


def balanced(depth: int, bl: float = 1.0) -> Tree:
    """A complete binary tree with ``2 ** depth`` leaves."""
    tree = Tree()
    frontier = [tree.root]
    for _ in range(depth):
        nxt = []
        for node in frontier:
            for _ in range(2):
                child = tree.new_node(None, bl)
                node.add_child(child)
                nxt.append(child)
        frontier = nxt
    for i, leaf in enumerate(frontier):
        leaf.name = f"leaf{i:04d}"
    tree.refresh()
    return tree


def bifurcating(n_leaves: int, bl: float = 0.05) -> Tree:
    """A balanced binary tree with exactly *n_leaves* leaves."""
    tree = Tree()
    frontier: list[tuple[Node, int]] = [(tree.root, n_leaves)]
    index = 0
    while frontier:
        node, k = frontier.pop()
        if k <= 1:
            node.name = f"tip{index:05d}"
            index += 1
            continue
        half = k // 2
        for part in (half, k - half):
            child = tree.new_node(None, bl)
            node.add_child(child)
            frontier.append((child, part))
    tree.refresh()
    return tree


def rows_of(frame, tree) -> dict[str, float]:
    """Row of every named node the frame laid out."""
    return {n.name: frame.row(n.id) for n in tree.nodes
            if n.name and frame.has(n.id)}


def xs_of(frame, tree) -> dict[str, float]:
    return {n.name: frame.x(n.id) for n in tree.nodes
            if n.name and frame.has(n.id)}


@pytest.fixture
def three_tips() -> Tree:
    return build(C(L("A", 0.5), L("B", 0.25), L("C", 1.0)))


@pytest.fixture
def unbalanced() -> Tree:
    """Binary, but with three leaves on the left and one on the right."""
    return build(C(
        C(C(L("A", 0.1), L("B", 0.1), bl=0.2), L("C", 0.3), bl=0.2, name="left"),
        L("D", 0.7),
    ))

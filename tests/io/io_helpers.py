# SPDX-License-Identifier: MIT
"""Shared helpers for the tree file I/O suite.

The corpus under ``fixtures/`` is entirely synthetic: every label was invented
for this project, and nothing was taken from another program's example data.
"""
from __future__ import annotations

from pathlib import Path

from makeyourtree.core.node import Node
from makeyourtree.core.traversal import preorder
from makeyourtree.core.tree import Tree

FIXTURES = Path(__file__).parent / "fixtures"

NEWICK_FILES = sorted(p.name for p in FIXTURES.glob("*.nwk"))
NEXUS_FILES = sorted(p.name for p in FIXTURES.glob("*.nex"))
XML_FILES = sorted(p.name for p in FIXTURES.glob("*.xml"))
ALL_FILES = NEWICK_FILES + NEXUS_FILES + XML_FILES


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def signature(tree: Tree) -> list[tuple]:
    """Everything a round trip must preserve: shape, labels, lengths, support.

    Depth is included so that two trees with the same labels in the same order
    but a different nesting cannot compare equal.
    """
    return [(n.level, n.name, n.branch_length, n.support, len(n.children))
            for n in preorder(tree.root)]


def caterpillar(n_leaves: int) -> Tree:
    """A fully pectinate tree -- the shape that breaks recursive parsers.

    Built iteratively for the same reason it is being tested.
    """
    root = Node("root")
    cur = root
    for i in range(n_leaves - 1):
        cur.add_child(Node(f"t{i}", 0.1))
        nxt = Node(None, 0.2)
        cur.add_child(nxt)
        cur = nxt
    cur.name = f"t{n_leaves - 1}"
    tree = Tree(root)
    tree.refresh()
    return tree


def sample_tree() -> Tree:
    root = Node("root")
    inner = Node(None, 0.3, 88.0)
    inner.add_child(Node("Alpha", 0.1))
    inner.add_child(Node("Beta", 0.2))
    root.add_child(inner)
    root.add_child(Node("Gamma", 0.4))
    tree = Tree(root, name="fixture")
    tree.refresh()
    return tree

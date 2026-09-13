# SPDX-License-Identifier: MIT
"""Shared helpers for the circular, radial and unrooted layout suite.

Trees are generated here rather than loaded from files: the properties under
test (angle spans, planarity, length preservation) are structural, so a seeded
random topology exercises them far harder than any fixture file would, and
generated data carries no third-party provenance.
"""

from __future__ import annotations

import math
import random

from makeyourtree.core.node import Node
from makeyourtree.core.tree import Tree


def make_tree(root: Node) -> Tree:
    tree = Tree(root)
    tree.refresh()
    return tree


def balanced(depth: int, length: float = 1.0) -> Tree:
    """Complete binary tree of ``2**depth`` leaves, every edge the same length."""
    counter = [0]

    def leaf() -> Node:
        counter[0] += 1
        return Node(f"t{counter[0]}", length)

    level = [leaf() for _ in range(2 ** depth)]
    while len(level) > 1:
        nxt: list[Node] = []
        for i in range(0, len(level), 2):
            parent = Node(None, length)
            parent.add_child(level[i])
            parent.add_child(level[i + 1])
            nxt.append(parent)
        level = nxt
    level[0].branch_length = None
    return make_tree(level[0])


def caterpillar(n_leaves: int, length: float = 0.5) -> Tree:
    """Fully pectinate tree -- the shape that breaks recursive implementations."""
    root = Node()
    cursor = root
    for i in range(n_leaves - 1):
        cursor.add_child(Node(f"t{i}", length))
        nxt = Node(None, length)
        cursor.add_child(nxt)
        cursor = nxt
    cursor.name = f"t{n_leaves - 1}"
    return make_tree(root)


def random_tree(n_leaves: int, seed: int = 0, lo: float = 0.05,
                hi: float = 2.0, polytomy: float = 0.0) -> Tree:
    """Random topology with random positive branch lengths.

    Grown by repeatedly splitting a uniformly chosen leaf, which produces the
    lopsided shapes that stress equal-angle's wedge arithmetic.  With
    *polytomy* > 0 some splits produce three children instead of two.
    """
    rng = random.Random(seed)
    root = Node()
    leaves = [root]
    while len(leaves) < n_leaves:
        target = leaves.pop(rng.randrange(len(leaves)))
        k = 3 if (polytomy and rng.random() < polytomy
                  and len(leaves) + 3 <= n_leaves + 1) else 2
        for _ in range(k):
            child = Node(None, round(rng.uniform(lo, hi), 6))
            target.add_child(child)
            leaves.append(child)
    for i, leaf in enumerate(leaves):
        leaf.name = f"taxon_{i:03d}"
    return make_tree(root)


def star(n_leaves: int, length: float = 1.0) -> Tree:
    root = Node()
    for i in range(n_leaves):
        root.add_child(Node(f"s{i}", length))
    return make_tree(root)


def tip_angles(frame) -> list[float]:
    """Scene angle of every visible tip, in row order."""
    return [frame.angle(tid) for tid in frame.tips]


def edge_pairs(tree) -> list[tuple[int, int]]:
    """``(parent_id, child_id)`` for every visible edge."""
    from makeyourtree.core.traversal import descend, preorder
    out = []
    for n in preorder(tree.root, visible_only=True):
        for c in descend(n, True):
            out.append((n.id, c.id))
    return out


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def named(name: str | None, length: float | None, *kids: Node) -> Node:
    n = Node(name, length)
    for k in kids:
        n.add_child(k)
    return n

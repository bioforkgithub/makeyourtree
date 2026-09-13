# SPDX-License-Identifier: MIT
"""Helpers shared by the dock-panel tests.

Kept in a uniquely named module rather than in ``conftest.py`` for the reason
spelled out in ``tests/render/conftest.py``: with pytest's prepend import mode
every test directory lands on ``sys.path`` and a bare ``conftest`` import would
compete for one entry in ``sys.modules``.
"""

from __future__ import annotations

from makeyourtree.core.node import Node
from makeyourtree.core.tree import Tree
from makeyourtree.doc.document import Document
from makeyourtree.io import load_tree
from makeyourtree.tracks.strip import ColorStripTrack

SAMPLE_NEWICK = (
    "(((a:0.1,b:0.2)ab:0.3,(c:0.4,d:0.5)cd:0.6)abcd:0.7,"
    "(e:0.8,f:0.9)ef:1.0)root;"
)


def sample_tree() -> Tree:
    """A six-leaf tree with names, lengths, supports and one attribute.

    Small enough to reason about by hand and asymmetric enough that ladderize,
    rotate and reroot all produce a visible change.
    """
    tree = load_tree(SAMPLE_NEWICK)
    for name, support in (("ab", 98.0), ("cd", 71.0), ("abcd", 55.0),
                          ("ef", 100.0)):
        node = tree.by_name(name)
        assert node is not None
        node.support = support
    leaf_a = tree.by_name("a")
    assert leaf_a is not None
    leaf_a.attrs["habitat"] = "marine"
    leaf_a.attrs["accession"] = "X12345"
    tree.refresh()
    return tree


def sample_document() -> Document:
    return Document(tree=sample_tree(), title="sample")


def strip_track(tree: Tree, *, title: str = "Region") -> ColorStripTrack:
    """A colour strip bound to a couple of the sample tree's leaves."""
    track = ColorStripTrack(title=title)
    track.bind(tree, {"a": ["north"], "b": ["south"]}, columns=["region"])
    return track


def balanced_tree(n_leaves: int) -> Tree:
    """A balanced binary tree with *n_leaves* leaves, built bottom-up.

    Bottom-up rather than by parsing a Newick string: 20 000 leaves is a 300 kB
    string and the parser is not what these tests are measuring.
    """
    tree = Tree(Node())
    level: list[Node] = [tree.new_node("leaf%d" % i, 0.1) for i in range(n_leaves)]
    while len(level) > 1:
        nxt: list[Node] = []
        for i in range(0, len(level) - 1, 2):
            parent = tree.new_node(None, 0.1)
            parent.add_child(level[i])
            parent.add_child(level[i + 1])
            nxt.append(parent)
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    tree.root = level[0]
    tree.root.branch_length = None
    tree.reindex()
    return tree


class Counter:
    """Counts signal emissions, so a test can assert "exactly one, not a loop"."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self, *_args: object) -> None:
        self.n += 1

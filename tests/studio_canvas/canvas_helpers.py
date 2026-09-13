# SPDX-License-Identifier: MIT
"""Tree and session builders shared by the canvas tests."""

from __future__ import annotations

from makeyourtree.core.tree import Tree
from makeyourtree.doc.document import Document
from makeyourtree.layout.params import LayoutMode
from makeyourtree.text.metrics import CachedMetrics

from makeyourtree_studio.canvas.qt_metrics import QtMetrics
from makeyourtree_studio.session import Session

NEWICK = "((a:0.4,b:0.2)ab:0.3,((c:0.1,d:0.6)cd:0.2,e:0.5)cde:0.15)root;"

ALL_MODES = (LayoutMode.RECTANGULAR, LayoutMode.SLANTED, LayoutMode.CIRCULAR,
             LayoutMode.RADIAL, LayoutMode.UNROOTED)


def balanced_tree(n_leaves: int) -> Tree:
    """A complete binary tree with *n_leaves* named tips.

    Built bottom-up rather than parsed from Newick so a 5000-leaf case costs
    milliseconds and the performance tests stay cheap enough to keep running.
    """
    tree = Tree()
    level = [tree.new_node(name=f"tip{i:05d}", branch_length=0.1 + (i % 7) * 0.05)
             for i in range(n_leaves)]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            parent = tree.new_node(branch_length=0.2)
            parent.add_child(level[i])
            parent.add_child(level[i + 1])
            nxt.append(parent)
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    tree.root = level[0]
    tree.touch()
    tree.refresh()
    return tree


def make_session(tree: Tree | None = None, *, mode: LayoutMode | None = None,
                 metrics: bool = True) -> Session:
    """A session over *tree* with Qt-backed metrics injected, as the app does."""
    doc = Document(tree=tree if tree is not None else Tree.from_newick(NEWICK))
    if mode is not None:
        doc.params.mode = mode
    session = Session(doc)
    if metrics:
        session.metrics = CachedMetrics(QtMetrics())
    return session

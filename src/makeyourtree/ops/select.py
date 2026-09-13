# SPDX-License-Identifier: MIT
"""Selection queries.

Pure reads: nothing here returns a :class:`~makeyourtree.ops.command.Command`, because
nothing here changes the tree.  Selection lives in ``ops`` all the same, since the
studio's selection tools and the CLI's ``--select`` expressions want one vocabulary
for "which nodes do you mean", and the answer is always a list of nodes in a
predictable order.

Order is the tree's own left-to-right order (preorder for clades, tip order for
leaves), so a selection can be handed straight to a track or a highlight layer
without sorting.  Every query returns a fresh list, never a view, so callers may
mutate the result.
"""

from __future__ import annotations

from typing import Any

from ..core.node import Node
from ..core.traversal import iter_leaves, preorder
from ..core.tree import Tree

__all__ = ["select_clade", "select_leaves", "select_path", "select_by_name"]


def select_clade(tree: Tree, node: Node | int | str, *,
                 visible_only: bool = False) -> list[Node]:
    """Every node at or below *node*, in preorder, including *node* itself.

    With *visible_only* the walk honours ``hidden`` and stops at ``collapsed``
    nodes, which is what a click on the canvas should select: what the user can see.
    """
    n = tree.resolve(node)
    return list(preorder(n, visible_only))


def select_leaves(tree: Tree, node: Node | int | str, *,
                  visible_only: bool = False) -> list[Node]:
    """The leaves below *node*, left to right; ``[node]`` when *node* is a leaf.

    With *visible_only* this yields visible tips instead -- real leaves plus
    collapsed clades -- because those are the entities that occupy layout rows.
    """
    n = tree.resolve(node)
    return list(iter_leaves(n, visible_only))


def select_path(tree: Tree, a: Node | int | str, b: Node | int | str) -> list[Node]:
    """The nodes from *a* up to the MRCA and back down to *b*, inclusive.

    The order is walkable: consecutive entries are always adjacent in the tree, so
    the result can be turned into an edge list by pairing neighbours.
    """
    return tree.path(a, b)


def select_by_name(tree: Tree, query: str, **kw: Any) -> list[Node]:
    """Nodes whose label (or another field) matches *query*.

    Delegates to :meth:`Tree.search`, which owns the matching rules; the keyword
    arguments are its own -- ``regex``, ``case_sensitive``, ``whole_word``,
    ``fields`` and ``leaves_only``.  Wrapped rather than aliased so that selection
    has a single import site and so that search gains no dependency on ``ops``.
    """
    return tree.search(query, **kw)

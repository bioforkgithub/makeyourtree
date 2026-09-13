# SPDX-License-Identifier: MIT
"""Child-order operations: ladderize, rotate, sort.

These edits move nothing but the contents of ``children`` lists.  No branch
length, no parent pointer, no leaf set changes, which is why they declare
``touches_topology = False`` and ``touches_order = True``: only the *cross*
coordinate of the layout (y in linear modes, angle in polar) depends on tip
order, so the canvas can reassign rows without recomputing the along coordinate
at all.  See the layout invariant in ``docs/SPEC.md`` section 2.1.

Why the tie-breakers are not optional
-------------------------------------
``list.sort`` is stable, so a comparison key that ties leaves the two subtrees in
whatever order the parser happened to emit.  Ladderizing a tree read from two
files that describe the same topology in different orders would then give two
different pictures, and ladderizing twice in a row could change the picture again.
Every key here therefore ends in the node id, which is unique, making the sort a
total order: the result depends on the topology alone and running it again is a
no-op.  ``tests/ops`` asserts that idempotence directly.

The subtree statistics used as keys -- leaf count, height in edges, greatest
cumulative length to a descendant leaf, and alphabetically first leaf name -- are
all accumulated in a single postorder sweep, following the standard bottom-up
formulation used for tidy-tree layout (Reingold and Tilford, "Tidier drawings of
trees", *IEEE Trans. Softw. Eng.* SE-7 (1981), 223-228).
"""

from __future__ import annotations

from typing import Any, Callable

from ..core.errors import OperationError
from ..core.node import Node
from ..core.traversal import postorder, preorder
from ..core.tree import Tree
from .command import Command

__all__ = ["ladderize", "rotate", "sort_children"]

SortKey = Callable[[Node], Any]

_KEY_ALIASES = {"size": "size", "leaves": "size", "depth": "depth",
                "height": "depth", "len": "len", "length": "len", "name": "name"}


class _Stats:
    """Per-subtree summaries used as sort keys, indexed by ``id(node)``.

    Keyed on ``id`` rather than written onto the nodes because ladderize must not
    disturb the derived caches that :meth:`Tree.refresh` owns; two of these four
    quantities are not among them anyway.
    """

    __slots__ = ("n_leaves", "height", "max_len", "min_name")

    def __init__(self, root: Node) -> None:
        self.n_leaves: dict[int, int] = {}
        self.height: dict[int, int] = {}
        self.max_len: dict[int, float] = {}
        self.min_name: dict[int, str] = {}
        for n in postorder(root):
            k = id(n)
            if not n.children:
                self.n_leaves[k] = 1
                self.height[k] = 0
                self.max_len[k] = 0.0
                self.min_name[k] = n.name or ""
            else:
                self.n_leaves[k] = sum(self.n_leaves[id(c)] for c in n.children)
                self.height[k] = 1 + max(self.height[id(c)] for c in n.children)
                self.max_len[k] = max(self.max_len[id(c)] + c.edge_length(0.0)
                                      for c in n.children)
                self.min_name[k] = min(self.min_name[id(c)] for c in n.children)


def _key_func(key: str | SortKey, stats: _Stats) -> SortKey:
    """Build a total-order sort key.  A caller-supplied callable is wrapped rather
    than trusted, so that user keys inherit the same id tie-break."""
    if callable(key):
        return lambda c: (key(c), c.id)
    kind = _KEY_ALIASES.get(key)
    if kind is None:
        raise OperationError(
            f"unknown ordering key {key!r}; expected one of "
            + ", ".join(sorted(set(_KEY_ALIASES))))
    if kind == "size":
        return lambda c: (stats.n_leaves[id(c)], stats.height[id(c)],
                          stats.min_name[id(c)], c.id)
    if kind == "depth":
        return lambda c: (stats.height[id(c)], stats.n_leaves[id(c)],
                          stats.min_name[id(c)], c.id)
    if kind == "len":
        return lambda c: (stats.max_len[id(c)], stats.n_leaves[id(c)],
                          stats.min_name[id(c)], c.id)
    return lambda c: (stats.min_name[id(c)], c.id)


class _OrderCommand(Command):
    """Base for edits that only permute child lists.

    Subclasses produce the new order; undo simply reinstates the recorded old
    lists, which is the whole of the state a reordering needs -- never coordinates.
    """

    touches_topology = False
    touches_order = True

    def __init__(self, label: str) -> None:
        self._changes: list[tuple[Node, tuple[Node, ...]]] = []
        self.label = label

    def _reorder(self, node: Node, new_order: list[Node]) -> None:
        old = tuple(node.children)
        if list(new_order) != list(old):
            self._changes.append((node, old))
            node.children[:] = new_order

    def undo(self, tree: Tree) -> None:
        for node, old in reversed(self._changes):
            node.children[:] = old
        self._changes = []
        tree.touch()


class _LadderizeCommand(_OrderCommand):
    def __init__(self, ascending: bool, key: str | SortKey, label: str) -> None:
        super().__init__(label)
        self._ascending = ascending
        self._key = key

    def apply(self, tree: Tree) -> None:
        self._changes = []
        stats = _Stats(tree.root)
        keyf = _key_func(self._key, stats)
        reverse = not self._ascending
        for n in preorder(tree.root):
            if len(n.children) > 1:
                self._reorder(n, sorted(n.children, key=keyf, reverse=reverse))
        tree.touch()


def ladderize(tree: Tree, ascending: bool = True, key: str | SortKey = "size") -> Command:
    """Order every node's children so the tree combs to one side.

    *key* selects what "smaller" means: ``"size"`` (leaf count), ``"depth"``
    (height in edges), ``"len"`` (greatest cumulative branch length to a
    descendant leaf) or ``"name"`` (alphabetically first leaf name).  A callable
    taking a node is also accepted.  ``ascending`` puts the smaller subtree first,
    which draws as a ladder descending to the right in a standard rectangular
    layout; ``False`` mirrors it.

    Apply this *after* rerooting, never before: rerooting rewrites the leaf counts
    and heights of every node on the path between the old and new roots, so an
    order chosen beforehand is no longer the ladderized one.
    """
    if not callable(key) and key not in _KEY_ALIASES:
        raise OperationError(
            f"unknown ordering key {key!r}; expected one of "
            + ", ".join(sorted(set(_KEY_ALIASES))))
    which = "ascending" if ascending else "descending"
    return _LadderizeCommand(ascending, key, f"ladderize ({which})")


class _RotateCommand(_OrderCommand):
    """Reverse one node's children.

    Reversing is an involution, so apply and undo are the same operation; there is
    no state to record.  Under the parent-coordinate rule that places a node at the
    midpoint of its extreme children, reversing a child list mirrors the subtree
    about the centre of its own leaf span, leaving that span -- and therefore every
    ancestor's cross coordinate -- untouched.
    """

    def __init__(self, node: Node, label: str) -> None:
        super().__init__(label)
        self._node = node

    def apply(self, tree: Tree) -> None:
        self._node.children.reverse()
        tree.touch()

    def undo(self, tree: Tree) -> None:
        self._node.children.reverse()
        tree.touch()


def rotate(tree: Tree, node: Node | int | str) -> Command:
    """Reverse the order of one node's children."""
    n = tree.resolve(node)
    if len(n.children) < 2:
        raise OperationError(f"nothing to rotate: {n!r} has fewer than two children")
    return _RotateCommand(n, f"rotate {n.name or n.id}")


class _SortChildrenCommand(_OrderCommand):
    def __init__(self, node: Node, key: str | SortKey, ascending: bool,
                 label: str) -> None:
        super().__init__(label)
        self._node = node
        self._key = key
        self._ascending = ascending

    def apply(self, tree: Tree) -> None:
        self._changes = []
        # Statistics only over this node's own subtree: the keys never look outside it.
        stats = _Stats(self._node)
        keyf = _key_func(self._key, stats)
        self._reorder(self._node, sorted(self._node.children, key=keyf,
                                         reverse=not self._ascending))
        tree.touch()


def sort_children(tree: Tree, node: Node | int | str, key: str | SortKey = "size",
                  ascending: bool = True) -> Command:
    """Reorder one node's children only, leaving the rest of the tree alone.

    The local counterpart of :func:`ladderize`, for a user who wants one clade
    tidied without redrawing the whole figure.
    """
    n = tree.resolve(node)
    if not callable(key) and key not in _KEY_ALIASES:
        raise OperationError(
            f"unknown ordering key {key!r}; expected one of "
            + ", ".join(sorted(set(_KEY_ALIASES))))
    return _SortChildrenCommand(n, key, ascending, f"sort children of {n.name or n.id}")

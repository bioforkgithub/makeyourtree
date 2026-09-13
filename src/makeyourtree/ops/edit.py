# SPDX-License-Identifier: MIT
"""Structural tree edits, each returned as a reversible :class:`Command`.

This module also owns the structural undo primitives that :mod:`makeyourtree.ops.rooting`
reuses.  They live here because every edit that rewires parent pointers -- pruning,
node deletion, suppression of degree-two nodes, rerooting -- needs exactly the same
thing: remember the four fields that describe a node's place in the tree
(``parent``, ``children``, ``branch_length``, ``support``) for the handful of nodes
that are about to change, and nothing else.  A whole-tree snapshot would be correct
too, but on a 100 000-leaf tree it costs real memory for every history entry.

Length and support merging follows the edge invariant stated in
:mod:`makeyourtree.core.node`: both fields describe the edge *parent -> self*.  When two
edges are fused into one -- suppressing a degree-two node -- the lengths add, because
the fused edge spans both; the supports do not add, because the two edges induced the
*same* bipartition (a node with one child splits the leaf set exactly as its child
does), so the surviving value is simply whichever of the two was recorded.

Reference for the suppression rule and for the equivalence of rooted and unrooted
representations: Felsenstein, *Inferring Phylogenies* (Sinauer, 2004), ch. 4.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from ..core.errors import OperationError
from ..core.node import Node
from ..core.traversal import iter_leaves, preorder
from ..core.tree import Tree
from .command import Command

__all__ = ["collapse", "expand", "prune", "delete_node", "extract_subtree",
           "collapse_singletons", "rename"]


@dataclass(slots=True)
class _NodeState:
    """The structural fields of one node, as they were before an edit."""

    node: Node
    parent: Node | None
    children: tuple[Node, ...]
    branch_length: float | None
    support: float | None


class _Recorder:
    """Lazily snapshots nodes the first time an edit is about to change one.

    Call :meth:`record` immediately *before* mutating a node.  Recording is
    idempotent per node, so the snapshot always holds the state from before the
    whole operation even when a node is touched several times -- which happens in
    rerooting, where a node on the reversal path is rewired and then suppressed.

    Because every recorded state names both the parent pointer and the full child
    list, :meth:`restore` is order-independent: it does not replay the edit
    backwards step by step, it reinstates a consistent set of links in one pass.
    """

    __slots__ = ("_states", "_seen")

    def __init__(self) -> None:
        self._states: list[_NodeState] = []
        self._seen: set[int] = set()

    def record(self, *nodes: Node) -> None:
        for n in nodes:
            key = id(n)
            if key not in self._seen:
                self._seen.add(key)
                self._states.append(
                    _NodeState(n, n.parent, tuple(n.children),
                               n.branch_length, n.support))

    def restore(self) -> None:
        for st in self._states:
            st.node.parent = st.parent
            st.node.children[:] = st.children
            st.node.branch_length = st.branch_length
            st.node.support = st.support

    def __len__(self) -> int:
        return len(self._states)


def _sum_lengths(a: float | None, b: float | None) -> float | None:
    """Fuse two edge lengths.  ``None`` means "the file gave no length", and two
    absent lengths fuse to an absent length rather than to a spurious zero."""
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


def _merge_support(child: float | None, parent: float | None) -> float | None:
    """Support of the edge left behind when a degree-two node is suppressed."""
    return child if child is not None else parent


def _suppress_one(v: Node, rec: _Recorder) -> bool:
    """Splice out *v* if it has a parent and exactly one child, fusing the edges.

    Returns False and changes nothing when *v* is not a degree-two node, so callers
    may offer it every candidate without checking first.
    """
    p = v.parent
    if p is None or len(v.children) != 1:
        return False
    c = v.children[0]
    rec.record(v, p, c)
    c.branch_length = _sum_lengths(c.branch_length, v.branch_length)
    c.support = _merge_support(c.support, v.support)
    p.children[p.children.index(v)] = c
    c.parent = p
    v.children.clear()
    v.parent = None
    return True


def _depth_from_root(n: Node) -> int:
    """Edge count to the root, walked live -- ``Node.level`` may be stale mid-edit."""
    d = 0
    cur = n.parent
    while cur is not None:
        d += 1
        cur = cur.parent
    return d


class _FlagCommand(Command):
    """Toggle ``collapsed`` on one node."""

    touches_topology = True
    touches_order = False

    def __init__(self, node: Node, collapsed: bool, label: str) -> None:
        self._node = node
        self._new = collapsed
        self._old = node.collapsed
        self.label = label

    def apply(self, tree: Tree) -> None:
        self._old = self._node.collapsed
        self._node.collapsed = self._new
        tree.touch()

    def undo(self, tree: Tree) -> None:
        self._node.collapsed = self._old
        tree.touch()


def collapse(tree: Tree, node: Node | int | str, collapsed: bool = True) -> Command:
    """Draw *node*'s subtree as a single summary shape, or stop doing so.

    Marked as touching topology even though no link changes: a collapsed clade
    stops occupying one row per leaf, so every tip row below it moves, and the
    summary wedge's extent depends on the along coordinate as well.  Skipping the
    relayout would be wrong in both coordinates.
    """
    n = tree.resolve(node)
    if not n.children:
        raise OperationError(f"cannot collapse a leaf: {n!r}")
    what = "collapse" if collapsed else "expand"
    return _FlagCommand(n, collapsed, f"{what} {n.name or n.id}")


def expand(tree: Tree, node: Node | int | str) -> Command:
    """Show *node*'s subtree in full again."""
    return collapse(tree, node, collapsed=False)


class _RenameCommand(Command):
    touches_topology = False
    touches_order = False

    def __init__(self, node: Node, name: str | None) -> None:
        self._node = node
        self._new = name
        self._old = node.name
        self.label = f"rename to {name!r}" if name else "clear name"

    def apply(self, tree: Tree) -> None:
        self._old = self._node.name
        self._node.name = self._new
        tree.touch()

    def undo(self, tree: Tree) -> None:
        self._node.name = self._old
        tree.touch()


def rename(tree: Tree, node: Node | int | str, name: str | None) -> Command:
    """Set a node's label; ``None`` clears it.

    ``touch()`` matters here even though nothing structural moved: the name index
    is keyed on the old string and would keep resolving it otherwise.
    """
    return _RenameCommand(tree.resolve(node), name)


class _DeleteCommand(Command):
    touches_topology = True

    def __init__(self, node: Node) -> None:
        self._node = node
        self._rec: _Recorder | None = None
        self.label = f"delete {node.name or node.id}"

    def apply(self, tree: Tree) -> None:
        n = self._node
        p = n.parent
        if p is None:
            raise OperationError("cannot delete the root; reroot or prune instead")
        rec = _Recorder()
        rec.record(n, p, *n.children)
        kids = list(n.children)
        unary = len(kids) == 1
        for c in kids:
            c.branch_length = _sum_lengths(c.branch_length, n.branch_length)
            if unary:
                c.support = _merge_support(c.support, n.support)
            c.parent = p
        i = p.children.index(n)
        p.children[i:i + 1] = kids
        n.children.clear()
        n.parent = None
        self._rec = rec
        tree.touch()

    def undo(self, tree: Tree) -> None:
        assert self._rec is not None
        self._rec.restore()
        tree.touch()


def delete_node(tree: Tree, node: Node | int | str) -> Command:
    """Remove one node, re-attaching its children to its parent in its place.

    Each child's edge absorbs the deleted node's edge length, which keeps every leaf
    at the same distance from the root -- the tips do not move in the drawing.  It
    does not keep the distance *between* two of those children fixed, and nothing
    could: the branching point where their paths met has been deleted, so the shared
    stretch of edge is now travelled twice instead of once.  Deleting a degree-two
    node is the case where both hold, and is what :func:`collapse_singletons` does.

    Support carries over only when the node had a single child, because only then do
    the two fused edges describe the same bipartition; deleting a real branching node
    destroys the split it stood for, and keeping its number would silently reattach
    it to a different bipartition.
    """
    return _DeleteCommand(tree.resolve(node))


class _PruneCommand(Command):
    touches_topology = True

    def __init__(self, roots: list[Node], label: str) -> None:
        self._roots = roots
        self._rec: _Recorder | None = None
        self._old_root: Node | None = None
        self.label = label

    def apply(self, tree: Tree) -> None:
        # Validate before touching anything: a command that raises halfway through
        # leaves a tree its own undo cannot describe.
        if any(r.parent is None for r in self._roots):
            raise OperationError("cannot prune the root")

        rec = _Recorder()
        self._old_root = tree.root

        candidates: list[Node] = []
        for r in self._roots:
            p = r.parent
            assert p is not None
            rec.record(r, p)
            p.children.remove(r)
            r.parent = None
            candidates.append(p)

        # Cascade upward: an internal node that lost every child is not a taxon,
        # it is an empty husk that would otherwise render as an unnamed tip.  Its
        # own parent then becomes a suppression candidate in turn.
        work = deque(candidates)
        while work:
            v = work.popleft()
            if v.parent is not None and not v.children:
                p = v.parent
                rec.record(v, p)
                p.children.remove(v)
                v.parent = None
                work.append(p)
                candidates.append(p)

        # Suppress the degree-two nodes the removals left behind.  Deepest first,
        # so that a chain of them collapses in a single pass.
        for v in sorted(candidates, key=_depth_from_root, reverse=True):
            _suppress_one(v, rec)

        # A root left with a single child is a stem, not a branching point, and its
        # edge leads nowhere; promote the child so the result is a real tree.
        root = tree.root
        while len(root.children) == 1:
            c = root.children[0]
            rec.record(root, c)
            root.children.clear()
            c.parent = None
            c.branch_length = None
            c.support = None
            tree.root = root = c

        self._rec = rec
        tree.touch()

    def undo(self, tree: Tree) -> None:
        assert self._rec is not None and self._old_root is not None
        self._rec.restore()
        tree.root = self._old_root
        tree.touch()


def prune(tree: Tree, nodes: Iterable[Node | int | str]) -> Command:
    """Remove taxa (or whole clades) and tidy up after them.

    Removing a leaf can leave its parent with one child; that node no longer
    represents a split and is spliced out with its edge length added to the
    surviving edge, which is exactly what keeps every distance between the
    *remaining* taxa as it was.  Nodes nested inside another node being removed are
    dropped from the request, since removing the ancestor already removes them.
    """
    targets = [tree.resolve(n) for n in nodes]
    if not targets:
        raise OperationError("prune() needs at least one node")
    marked = {id(n) for n in targets}
    roots: list[Node] = []
    seen: set[int] = set()
    for n in targets:
        if id(n) in seen:
            continue
        seen.add(id(n))
        if any(id(a) in marked for a in n.iter_ancestors()):
            continue
        if n.parent is None:
            raise OperationError("cannot prune the root")
        roots.append(n)

    doomed = sum(1 for r in roots for _ in iter_leaves(r))
    if doomed >= tree.n_leaves:
        raise OperationError("pruning would remove every taxon")
    label = (f"prune {len(roots)} nodes" if len(roots) > 1
             else f"prune {roots[0].name or roots[0].id}")
    return _PruneCommand(roots, label)


class _CollapseSingletonsCommand(Command):
    touches_topology = True

    def __init__(self) -> None:
        self._rec: _Recorder | None = None
        self.label = "remove single-child nodes"

    def apply(self, tree: Tree) -> None:
        rec = _Recorder()
        # Preorder gives parents before children, so a chain of unary nodes is
        # spliced from the top down and every survivor is still linked in when its
        # own turn comes.  The list() is deliberate: the walk mutates the tree.
        for n in list(preorder(tree.root)):
            _suppress_one(n, rec)
        self._rec = rec
        tree.touch()

    def undo(self, tree: Tree) -> None:
        assert self._rec is not None
        self._rec.restore()
        tree.touch()


def collapse_singletons(tree: Tree) -> Command:
    """Splice out every internal node that has exactly one child.

    Such nodes carry no phylogenetic information -- they induce the same
    bipartition as their child -- but they do occur in real files, from ancestral
    state annotations and from other tools' pruning.  A root with a single child is
    left alone: it has degree one, not two, and removing it would change which node
    the tree is rooted on.
    """
    return _CollapseSingletonsCommand()


def extract_subtree(tree: Tree, node: Node | int | str) -> Tree:
    """Copy the clade at *node* into a new :class:`Tree`.

    Not a command: nothing in the source tree changes, so there is nothing to undo.
    Node ids are preserved so that styles, annotation tables and track data keyed on
    them keep matching.  The new root's branch length and support are dropped --
    they described the edge to a parent that the new tree does not have.
    """
    src = tree.resolve(node)
    new_root = src.shallow_copy()
    new_root.branch_length = None
    new_root.support = None
    stack: list[tuple[Node, Node]] = [(src, new_root)]
    while stack:
        s, d = stack.pop()
        for c in s.children:
            cc = c.shallow_copy()
            d.add_child(cc)
            stack.append((c, cc))
    out = Tree(new_root, name=src.name or tree.name, rooted=True)
    out.metadata = dict(tree.metadata)
    return out

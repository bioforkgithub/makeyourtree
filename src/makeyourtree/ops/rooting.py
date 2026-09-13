# SPDX-License-Identifier: MIT
"""Rerooting, midpoint rooting, outgroup rooting and unrooting.

THE EDGE RULE
-------------
``branch_length`` and ``support`` describe the edge *parent -> self*
(:mod:`makeyourtree.core.node`).  Rerooting reverses the direction of every edge on
the path from the new root to the old one.  For a reversed edge ``p -> c`` with
length ``x`` and support ``s``, the edge afterwards runs ``c -> p``, so ``x`` and
``s`` must be written onto ``p`` -- the node that is now the child.  Leaving them
on ``c`` is the classic rerooting bug: branch lengths shift by one edge along the
path and bootstrap values end up labelling the wrong bipartitions, with nothing
raising an error.  Two invariants pin this down and both are asserted in the test
suite: the total tree length is unchanged (one edge is merely split in two), and
the set of (bipartition, support) pairs is unchanged.

Algorithms
----------
* Edge reversal along the root path: the standard parent-pointer formulation, as
  described for rooted/unrooted interconversion in Felsenstein, *Inferring
  Phylogenies* (Sinauer, 2004), ch. 4.
* Midpoint rooting: Farris, "Estimating phylogenetic trees from distance
  matrices", *Am. Nat.* 106 (1972), 645-668 -- root at the midpoint of the longest
  leaf-to-leaf path.  The longest path is found with a single postorder dynamic
  program (for each node, the greatest distance down to a leaf, plus the best two
  child contributions), which is O(V), needs no adjacency copy of the tree, and --
  unlike the usual double-sweep diameter search -- stays exact when branch lengths
  are negative, as they are in neighbour-joining output.
* Outgroup rooting: root on the edge subtending the outgroup's MRCA, checking
  monophyly by leaf counts.
"""

from __future__ import annotations

import math
from typing import Iterable

from ..core.errors import OperationError
from ..core.node import Node
from ..core.traversal import iter_leaves, postorder
from ..core.tree import Tree
from .command import Command
from .edit import _Recorder, _suppress_one, _sum_lengths

__all__ = ["reroot_on_edge", "midpoint_root", "outgroup_root", "unroot"]

_EPS = 1e-12


def _split_length(total: float | None, dist_from_node: float | None
                  ) -> tuple[float | None, float | None]:
    """Divide an edge of length *total* at *dist_from_node* from the child end.

    An absent length stays absent on both halves: a cladogram must not acquire
    spurious zero-length branches just because it was rerooted.  The clamp uses
    ``min(0, total)``/``max(0, total)`` rather than ``0``/``total`` so that a
    negative edge length -- legal in distance-method output -- still yields two
    halves that sum back to the original.
    """
    if total is None:
        return None, None
    if dist_from_node is None:
        d1 = 0.5 * total
    else:
        lo, hi = min(0.0, total), max(0.0, total)
        d1 = min(max(dist_from_node, lo), hi)
    return d1, total - d1


class _RerootCommand(Command):
    """Insert a new root on the edge above one node, reversing the path above it."""

    touches_topology = True

    def __init__(self, node: Node, dist_from_node: float | None, label: str) -> None:
        self._node = node
        self._dist = dist_from_node
        self._rec: _Recorder | None = None
        self._old_root: Node | None = None
        self._old_rooted = True
        self._new_root: Node | None = None
        self.label = label

    def apply(self, tree: Tree) -> None:
        node = self._node
        p = node.parent
        if p is None:
            raise OperationError("cannot reroot on the edge above the root")

        rec = _Recorder()
        self._old_root = old_root = tree.root
        self._old_rooted = tree.rooted

        # Reuse the same node object (and therefore the same id) on redo, so that a
        # redone reroot is indistinguishable from the original.
        if self._new_root is None:
            self._new_root = tree.new_node()
        R = self._new_root
        R.parent = None
        R.children.clear()
        R.branch_length = None
        R.support = None

        d1, d2 = _split_length(node.branch_length, self._dist)

        # Detach `node` BEFORE walking up.  Otherwise the walk re-attaches p under R
        # while node is still listed among p's children, which makes a cycle -- and a
        # cycle in a parent-pointer tree hangs the next traversal with no error.
        rec.record(node, p)
        p.children.remove(node)
        R.children.append(node)
        node.parent = R
        node.branch_length = d1

        # The split edge keeps its support on both halves: they describe the same
        # bipartition, because inserting a degree-two node changes no leaf set.
        new_parent: Node = R
        cur: Node | None = p
        incoming: float | None = d2
        incoming_sup: float | None = node.support
        while cur is not None:
            nxt = cur.parent
            rec.record(cur)
            # Read the outgoing edge's fields before overwriting them; they belong to
            # the next edge up, which is about to be reversed in turn.
            nxt_len = cur.branch_length
            nxt_sup = cur.support
            if nxt is not None:
                rec.record(nxt)
                nxt.children.remove(cur)
            new_parent.children.append(cur)
            cur.parent = new_parent
            cur.branch_length = incoming
            cur.support = incoming_sup
            new_parent, cur = cur, nxt
            incoming, incoming_sup = nxt_len, nxt_sup

        # Every path node kept its child count (it lost one child and gained its old
        # parent); only the old root lost one outright.  If that left it with a single
        # child it is a degree-two artefact and must go, or the tree gains a fake
        # bifurcation.  With three or more children it is now an ordinary internal
        # node and is left alone -- handling only the first case corrupts polytomies.
        _suppress_one(old_root, rec)

        self._rec = rec
        tree.root = R
        tree.rooted = True
        tree.touch()

    def undo(self, tree: Tree) -> None:
        assert self._rec is not None and self._old_root is not None
        self._rec.restore()
        R = self._new_root
        if R is not None:
            R.parent = None
            R.children.clear()
        tree.root = self._old_root
        tree.rooted = self._old_rooted
        tree.touch()


def reroot_on_edge(tree: Tree, node: Node | int | str,
                   dist_from_node: float | None = None) -> Command:
    """Place the root on the edge ``parent(node) -> node``.

    *dist_from_node* is the distance from *node* to the new root; ``None`` means
    the middle of the edge.  It is clamped into the edge, so callers computing it
    from floating-point path sums cannot push the root off the end.

    This is the general primitive: :func:`midpoint_root` and :func:`outgroup_root`
    do nothing but choose the edge and the offset, then call this.
    """
    n = tree.resolve(node)
    if n.parent is None:
        raise OperationError("cannot reroot on the edge above the root")
    return _RerootCommand(n, dist_from_node, f"reroot above {n.name or n.id}")


def _edge_weight(a: Node, b: Node) -> float:
    """Length of the edge joining two adjacent nodes, whichever way it points."""
    return a.edge_length(0.0) if a.parent is b else b.edge_length(0.0)


def _longest_leaf_path(tree: Tree) -> tuple[Node, Node, float]:
    """Return the two most distant leaves and their patristic distance.

    One postorder pass.  ``down[v]`` is the greatest distance from *v* to a leaf in
    its own subtree; the longest leaf-to-leaf path has a unique topmost node, and at
    that node it is the sum of the two largest child contributions, so tracking the
    best such sum over all nodes finds it.  This works for negative branch lengths,
    where the classic double-sweep diameter search silently returns the wrong pair.
    """
    down: dict[int, float] = {}
    best_child: dict[int, Node] = {}
    best: tuple[float, Node | None, Node | None] = (-math.inf, None, None)
    for n in postorder(tree.root):
        if not n.children:
            down[id(n)] = 0.0
            continue
        c1: Node | None = None
        d1 = -math.inf
        c2: Node | None = None
        d2 = -math.inf
        for c in n.children:
            d = down[id(c)] + c.edge_length(0.0)
            if d > d1:
                c2, d2 = c1, d1
                c1, d1 = c, d
            elif d > d2:
                c2, d2 = c, d
        assert c1 is not None
        down[id(n)] = d1
        best_child[id(n)] = c1
        if c2 is not None and d1 + d2 > best[0]:
            best = (d1 + d2, c1, c2)

    if best[1] is None or best[2] is None:
        raise OperationError("midpoint rooting needs at least two leaves")

    def deepest(start: Node) -> Node:
        n = start
        while n.children:
            n = best_child[id(n)]
        return n

    return deepest(best[1]), deepest(best[2]), best[0]


def midpoint_root(tree: Tree) -> Command:
    """Root at the midpoint of the longest leaf-to-leaf path (Farris 1972).

    Wholly iterative: one postorder for the longest path, two parent walks to
    recover it, one linear scan along it.  A 100 000-leaf caterpillar has a
    100 000-edge path, so nothing here may recurse.

    The chosen point may fall on a terminal edge -- a single long tip can dominate
    the longest path -- and it may land exactly on an existing node, in which case
    the inserted root carries a zero-length branch on one side.  Both are correct
    and neither needs a special case: :func:`reroot_on_edge` suppresses the old
    root when it is left with one child, so no length is lost either way.
    """
    a, b, total = _longest_leaf_path(tree)

    # Recover the path a -> ... -> apex -> ... -> b through the two parent chains.
    seen: dict[int, int] = {}
    up_a: list[Node] = []
    cur: Node | None = a
    while cur is not None:
        seen[id(cur)] = len(up_a)
        up_a.append(cur)
        cur = cur.parent
    up_b: list[Node] = []
    cur = b
    while cur is not None and id(cur) not in seen:
        up_b.append(cur)
        cur = cur.parent
    if cur is None:
        raise OperationError("midpoint rooting: leaves do not share a root")
    path = up_a[:seen[id(cur)] + 1] + list(reversed(up_b))

    half = 0.5 * total
    acc = 0.0
    x, y, off, w = path[-2], path[-1], 0.0, 0.0
    for i in range(len(path) - 1):
        x, y = path[i], path[i + 1]
        w = _edge_weight(x, y)
        if acc + w >= half - _EPS:
            off = half - acc
            break
        acc += w
    else:  # only reachable with negative lengths, where the walk is not monotone
        off = w

    child, dist = (x, off) if x.parent is y else (y, w - off)
    return _RerootCommand(child, dist, "midpoint root")


def _outgroup_leaves(tree: Tree, outgroup: Iterable[Node | int | str]) -> list[Node]:
    """Resolve an outgroup specification to leaf nodes.

    Accepts leaves, internal nodes (taken as the clade they subtend), ids or names,
    so the studio can hand over whatever the user selected.
    """
    out: list[Node] = []
    seen: set[int] = set()
    for ref in outgroup:
        n = tree.resolve(ref)
        for lf in iter_leaves(n):
            if id(lf) not in seen:
                seen.add(id(lf))
                out.append(lf)
    return out


def outgroup_root(tree: Tree, outgroup: Iterable[Node | int | str],
                  at_fraction: float = 0.5) -> Command:
    """Root on the edge separating *outgroup* from everything else.

    *at_fraction* is measured from the outgroup end of that edge: 0.5 puts the root
    in the middle of the outgroup stem, 0.0 puts it at the outgroup node itself.

    The outgroup need only be monophyletic in the *unrooted* sense.  If its own MRCA
    subtends extra taxa, the complement is tried instead: when the ingroup is a clade,
    the edge above the ingroup is the very edge that separates the two sets, and the
    tree can be rooted there.  Only when neither side is a clade is the split absent
    from the tree, and then the offending taxa are named -- an outgroup that is nearly
    right is far more common than one that is nonsense, and the user needs to know
    which taxa broke it.
    """
    members = _outgroup_leaves(tree, outgroup)
    if not members:
        raise OperationError("outgroup_root() needs at least one taxon")
    marked = {id(lf) for lf in members}
    all_leaves = list(iter_leaves(tree.root))
    if len(members) >= len(all_leaves):
        raise OperationError("the outgroup contains every taxon in the tree")

    n_leaves = _leaf_counts(tree)
    split = tree.mrca(members)
    frac = at_fraction
    if n_leaves[id(split)] != len(members):
        complement = [lf for lf in all_leaves if id(lf) not in marked]
        alt = tree.mrca(complement)
        if n_leaves[id(alt)] == len(complement):
            # Rooting above the ingroup roots on the same edge, but the offset is
            # now measured from the other end of it.
            split, frac = alt, 1.0 - at_fraction
        else:
            intruders = sorted(lf.name or f"#{lf.id}" for lf in iter_leaves(split)
                               if id(lf) not in marked)
            shown = ", ".join(intruders[:8])
            more = "" if len(intruders) <= 8 else f", and {len(intruders) - 8} more"
            raise OperationError(
                "outgroup is not monophyletic: its most recent common ancestor "
                f"also subtends {shown}{more}")

    if split.parent is None:
        raise OperationError("outgroup spans the whole tree; there is no edge to root on")
    bl = split.branch_length
    dist = None if bl is None else frac * bl
    return _RerootCommand(split, dist, "outgroup root")


def _leaf_counts(tree: Tree) -> dict[int, int]:
    """Leaves at or below each node, by ``id()``.

    Computed here rather than read from ``Node.n_leaves`` so that the monophyly test
    does not depend on whether someone has called ``refresh()`` since the last edit.
    """
    counts: dict[int, int] = {}
    for n in postorder(tree.root):
        counts[id(n)] = 1 if not n.children else sum(counts[id(c)] for c in n.children)
    return counts


class _UnrootCommand(Command):
    touches_topology = True

    def __init__(self, label: str) -> None:
        self._rec: _Recorder | None = None
        self._old_root: Node | None = None
        self._old_rooted = True
        self.label = label

    def apply(self, tree: Tree) -> None:
        rec = _Recorder()
        self._old_root = root = tree.root
        self._old_rooted = tree.rooted

        if len(root.children) == 2:
            c1, c2 = root.children
            keeper, other = (c1, c2) if c1.children else (c2, c1)
            if not keeper.children:
                raise OperationError(
                    "cannot unroot a two-taxon tree: the result has no branching node")
            rec.record(root, keeper, other)
            # The two root edges describe one and the same bipartition, so their
            # lengths add onto the single surviving edge and the support carries over.
            other.branch_length = _sum_lengths(other.branch_length,
                                               keeper.branch_length)
            other.support = other.support if other.support is not None else keeper.support
            keeper.parent = None
            keeper.branch_length = None
            keeper.support = None
            keeper.children.append(other)
            other.parent = keeper
            root.children.clear()
            root.parent = None
            tree.root = keeper

        self._rec = rec
        tree.rooted = False
        tree.touch()

    def undo(self, tree: Tree) -> None:
        assert self._rec is not None and self._old_root is not None
        self._rec.restore()
        tree.root = self._old_root
        tree.rooted = self._old_rooted
        tree.touch()


def unroot(tree: Tree) -> Command:
    """Collapse a bifurcating root into a trifurcation.

    A rooted binary tree's root is a degree-two node that no data supports; the two
    edges below it are really one edge of the unrooted tree, so their lengths sum
    onto the survivor and no distance changes.  A root that already has three or
    more children is topologically unrooted, and the command then only clears the
    ``rooted`` flag -- which is what exporters and the unrooted layout consult.
    """
    return _UnrootCommand("unroot")

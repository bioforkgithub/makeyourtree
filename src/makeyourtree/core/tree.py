# SPDX-License-Identifier: MIT
"""The tree container: identity, indexes, derived statistics and queries.

A :class:`Tree` owns a root :class:`~makeyourtree.core.node.Node` plus the
bookkeeping that makes the rest of the system fast: a monotonically increasing
node-id counter, an id index, a name index, and a set of derived per-node
statistics recomputed in one pass by :meth:`Tree.refresh`.

Derived statistics contract
---------------------------
After ``refresh()`` every node carries:

``n_leaves``   number of topological leaves at or below it (a leaf counts 1)
``height``     longest path to a descendant leaf, measured in EDGES
``depth_len``  cumulative branch length from the root to this node
``level``      number of edges from the root (root is 0)

``span_lo`` / ``span_hi`` are *not* set here -- they describe visible row
occupancy and are written by the layout engine, which alone knows what is
collapsed.

Mutating structure invalidates these.  Callers mutate through
:mod:`makeyourtree.ops`, which calls :meth:`touch` for them; direct users of
``Node.add_child`` must call ``touch()`` themselves.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Iterator, Sequence

from .errors import OperationError
from .node import Node
from .traversal import iter_leaves, postorder, preorder

__all__ = ["Tree"]


class Tree:
    """A rooted or unrooted phylogeny with one designated root node.

    MakeYourTree always stores a root node, even for trees the source file declared
    unrooted -- an unrooted tree is simply one whose root is a polytomy of
    degree three or more and whose ``rooted`` flag is false.  Layouts and
    exporters consult ``rooted``; the data structure does not change.
    """

    __slots__ = ("root", "name", "rooted", "metadata", "_next_id", "_by_id",
                 "_by_name", "_nodes", "_dirty")

    def __init__(self, root: Node | None = None, *, name: str | None = None,
                 rooted: bool = True) -> None:
        self.name = name
        self.rooted = rooted
        self.metadata: dict[str, Any] = {}
        self._next_id = 0
        self._by_id: dict[int, Node] = {}
        self._by_name: dict[str, Node] = {}
        self._nodes: list[Node] | None = None
        self._dirty = True
        self.root = root if root is not None else Node()
        if self.root.id < 0:
            self.adopt(self.root)
        else:
            self.reindex()

    # ------------------------------------------------------------- identity

    def new_node(self, name: str | None = None, branch_length: float | None = None,
                 support: float | None = None, **kw: Any) -> Node:
        """Create a node owned by this tree, with a fresh unique id."""
        n = Node(name, branch_length, support, id=self._next_id, **kw)
        self._next_id += 1
        self._by_id[n.id] = n
        self._dirty = True
        return n

    def adopt(self, node: Node) -> Node:
        """Assign ids to *node* and any descendants that do not yet have one."""
        for n in preorder(node):
            if n.id < 0 or self._by_id.get(n.id) not in (None, n):
                n.id = self._next_id
                self._next_id += 1
            else:
                self._next_id = max(self._next_id, n.id + 1)
            self._by_id[n.id] = n
        self._dirty = True
        return node

    def reindex(self) -> None:
        """Rebuild id and name indexes from the current structure.

        Nodes that were detached are dropped from the indexes.  Ids of nodes
        still in the tree are preserved -- layout frames, style maps and
        annotation tables key on them.
        """
        by_id: dict[int, Node] = {}
        by_name: dict[str, Node] = {}
        nodes: list[Node] = []
        nxt = 0
        for n in preorder(self.root):
            if n.id < 0 or n.id in by_id:
                n.id = max(nxt, self._next_id)
                self._next_id = n.id + 1
            by_id[n.id] = n
            nxt = max(nxt, n.id + 1)
            if n.name and n.name not in by_name:
                by_name[n.name] = n
            nodes.append(n)
        self._next_id = max(self._next_id, nxt)
        self._by_id = by_id
        self._by_name = by_name
        self._nodes = nodes

    def touch(self) -> None:
        """Mark derived statistics and indexes stale."""
        self._dirty = True
        self._nodes = None

    # ------------------------------------------------------------- refresh

    def refresh(self) -> "Tree":
        """Recompute indexes and derived per-node statistics.  Idempotent, O(n)."""
        self.reindex()
        # Top-down: level and cumulative length.
        root = self.root
        root.level = 0
        root.depth_len = 0.0
        for n in preorder(root):
            base_level = n.level
            base_len = n.depth_len
            for c in n.children:
                c.level = base_level + 1
                c.depth_len = base_len + c.edge_length(0.0)
        # Bottom-up: leaf counts and edge height.
        for n in postorder(root):
            if not n.children:
                n.n_leaves = 1
                n.height = 0
            else:
                total = 0
                h = 0
                for c in n.children:
                    total += c.n_leaves
                    if c.height + 1 > h:
                        h = c.height + 1
                n.n_leaves = total
                n.height = h
        self._dirty = False
        return self

    def _ensure(self) -> None:
        if self._dirty:
            self.refresh()

    # --------------------------------------------------------------- access

    @property
    def nodes(self) -> list[Node]:
        """All nodes in preorder.  Cached; invalidated by :meth:`touch`."""
        if self._nodes is None:
            self.reindex()
        return self._nodes  # type: ignore[return-value]

    @property
    def leaves(self) -> list[Node]:
        """Topological leaves, left to right."""
        return list(iter_leaves(self.root))

    @property
    def tips(self) -> list[Node]:
        """Visible tips: leaves plus collapsed clades, left to right."""
        return list(iter_leaves(self.root, visible_only=True))

    @property
    def n_leaves(self) -> int:
        self._ensure()
        return self.root.n_leaves

    @property
    def n_nodes(self) -> int:
        return len(self.nodes)

    def by_id(self, node_id: int) -> Node | None:
        if self._nodes is None:
            self.reindex()
        return self._by_id.get(node_id)

    def by_name(self, name: str) -> Node | None:
        """First node carrying *name*, or ``None``.  Names need not be unique."""
        if self._nodes is None:
            self.reindex()
        return self._by_name.get(name)

    def __iter__(self) -> Iterator[Node]:
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)

    def __contains__(self, item: Node | int | str) -> bool:
        if isinstance(item, Node):
            return self.by_id(item.id) is item
        if isinstance(item, int):
            return self.by_id(item) is not None
        return self.by_name(item) is not None

    def resolve(self, ref: Node | int | str) -> Node:
        """Coerce a node, id or name into a node belonging to this tree."""
        if isinstance(ref, Node):
            return ref
        n = self.by_id(ref) if isinstance(ref, int) else self.by_name(ref)
        if n is None:
            raise OperationError(f"no such node: {ref!r}")
        return n

    # ---------------------------------------------------------------- search

    def search(self, query: str, *, regex: bool = False, case_sensitive: bool = False,
               whole_word: bool = False, fields: Sequence[str] = ("name",),
               leaves_only: bool = False) -> list[Node]:
        """Find nodes whose *fields* match *query*.

        ``fields`` may name ``"name"``, ``"comment"``, or any key in
        ``Node.attrs``.  Substring matching by default; set ``regex`` for a
        regular expression or ``whole_word`` to anchor the whole value.
        """
        if regex:
            rx = re.compile(query, 0 if case_sensitive else re.IGNORECASE)
            test = (lambda s: rx.fullmatch(s) is not None) if whole_word else \
                   (lambda s: rx.search(s) is not None)
        else:
            needle = query if case_sensitive else query.lower()

            def test(s: str) -> bool:
                hay = s if case_sensitive else s.lower()
                return hay == needle if whole_word else needle in hay

        out: list[Node] = []
        for n in preorder(self.root):
            if leaves_only and n.children:
                continue
            for f in fields:
                if f == "name":
                    v = n.name
                elif f == "comment":
                    v = n.comment
                else:
                    v = n.attrs.get(f)
                if v is not None and test(str(v)):
                    out.append(n)
                    break
        return out

    # ------------------------------------------------------------ topology

    def mrca(self, nodes: Iterable[Node | int | str]) -> Node:
        """Most recent common ancestor of one or more nodes.

        Folded pairwise: MRCA of a set is associative, so reducing with the
        two-node case is both correct and O(sum of path lengths).
        """
        it = [self.resolve(n) for n in nodes]
        if not it:
            raise OperationError("mrca() needs at least one node")
        acc = it[0]
        for n in it[1:]:
            acc = self._mrca2(acc, n)
        return acc

    @staticmethod
    def _mrca2(a: Node, b: Node) -> Node:
        """MRCA of exactly two nodes; a node is its own ancestor here."""
        seen: set[int] = set()
        cur: Node | None = a
        while cur is not None:
            seen.add(id(cur))
            cur = cur.parent
        cur = b
        while cur is not None and id(cur) not in seen:
            cur = cur.parent
        if cur is None:
            raise OperationError("nodes do not share a root")
        return cur

    @staticmethod
    def _is_descendant(node: Node, ancestor: Node) -> bool:
        cur = node.parent
        while cur is not None:
            if cur is ancestor:
                return True
            cur = cur.parent
        return False

    def path(self, a: Node | int | str, b: Node | int | str) -> list[Node]:
        """Node path from *a* to *b* inclusive, through their MRCA."""
        na, nb = self.resolve(a), self.resolve(b)
        anc = self.mrca([na, nb])
        up: list[Node] = []
        cur: Node | None = na
        while cur is not None and cur is not anc:
            up.append(cur)
            cur = cur.parent
        down: list[Node] = []
        cur = nb
        while cur is not None and cur is not anc:
            down.append(cur)
            cur = cur.parent
        return up + [anc] + list(reversed(down))

    def distance(self, a: Node | int | str, b: Node | int | str,
                 *, topological: bool = False) -> float:
        """Patristic distance: summed branch lengths along the path from *a* to *b*.

        With ``topological`` the edge count is returned instead.
        """
        na, nb = self.resolve(a), self.resolve(b)
        anc = self.mrca([na, nb])
        total = 0.0
        for start in (na, nb):
            cur = start
            while cur is not anc and cur.parent is not None:
                total += 1.0 if topological else cur.edge_length(0.0)
                cur = cur.parent
        return total

    # ---------------------------------------------------------- statistics

    @property
    def max_root_to_tip(self) -> float:
        """Largest cumulative branch length from the root to any leaf."""
        self._ensure()
        best = 0.0
        for lf in iter_leaves(self.root):
            if lf.depth_len > best:
                best = lf.depth_len
        return best

    @property
    def total_branch_length(self) -> float:
        return sum(n.edge_length(0.0) for n in self.nodes if n is not self.root)

    @property
    def has_branch_lengths(self) -> bool:
        return any(n.branch_length is not None for n in self.nodes if n is not self.root)

    @property
    def has_support(self) -> bool:
        return any(n.support is not None for n in self.nodes)

    @property
    def max_level(self) -> int:
        self._ensure()
        return max(n.level for n in self.nodes)

    def support_range(self) -> tuple[float, float] | None:
        """(min, max) over all present support values, or ``None`` if there are none."""
        vals = [n.support for n in self.nodes if n.support is not None]
        if not vals:
            return None
        return min(vals), max(vals)

    def is_ultrametric(self, tol: float = 1e-6) -> bool:
        """True when every leaf sits at the same root-to-tip distance."""
        self._ensure()
        ds = [lf.depth_len for lf in iter_leaves(self.root)]
        if not ds:
            return True
        return (max(ds) - min(ds)) <= tol * max(1.0, abs(max(ds)))

    def is_binary(self) -> bool:
        """True when every internal node has exactly two children.

        The root of an unrooted tree is allowed three children.
        """
        for n in self.nodes:
            k = len(n.children)
            if k == 0:
                continue
            if n is self.root and not self.rooted:
                if k not in (2, 3):
                    return False
            elif k != 2:
                return False
        return True

    def has_negative_lengths(self) -> bool:
        return any((n.branch_length or 0.0) < 0.0 for n in self.nodes)

    # -------------------------------------------------------------- copying

    def copy(self) -> "Tree":
        """Deep copy preserving node ids, so styles and tracks keep matching."""
        new_root = self.root.shallow_copy()
        stack = [(self.root, new_root)]
        while stack:
            src, dst = stack.pop()
            for c in src.children:
                cc = c.shallow_copy()
                dst.add_child(cc)
                stack.append((c, cc))
        t = Tree(new_root, name=self.name, rooted=self.rooted)
        t.metadata = dict(self.metadata)
        t._next_id = self._next_id
        t.reindex()
        return t

    # ---------------------------------------------------------------- misc

    def collapsed_nodes(self) -> list[Node]:
        return [n for n in self.nodes if n.collapsed and n.children]

    def expand_all(self) -> None:
        for n in self.nodes:
            n.collapsed = False

    def to_newick(self, **kw: Any) -> str:
        """Serialise to a Newick string.  Thin wrapper over :mod:`makeyourtree.io`."""
        from ..io import write_newick
        return write_newick(self, **kw)

    def __repr__(self) -> str:
        nm = f" {self.name!r}" if self.name else ""
        kind = "rooted" if self.rooted else "unrooted"
        return f"<Tree{nm} {kind} leaves={self.n_leaves} nodes={self.n_nodes}>"

    @classmethod
    def from_newick(cls, text: str, **kw: Any) -> "Tree":
        """Parse a Newick string.  Thin wrapper over :mod:`makeyourtree.io`."""
        from ..io import read_newick
        return read_newick(text, **kw)

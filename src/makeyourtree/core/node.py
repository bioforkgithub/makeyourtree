# SPDX-License-Identifier: MIT
"""The tree node.

INVARIANT THAT GOVERNS THE WHOLE CODEBASE
-----------------------------------------
``branch_length`` and ``support`` describe the EDGE that runs from ``parent`` to
this node -- they are not properties of the node itself.  They are stored on the
child purely because that is where a parent-pointer tree can hold them in O(1).
Every operation that reverses an edge (rerooting, unrooting, grafting) must move
``branch_length`` and ``support`` along with the edge, never leave them attached
to the node.  Getting this wrong is the most common source of bugs in tree
software.
"""

from __future__ import annotations

from typing import Any, Iterator

__all__ = ["Node"]


class Node:
    """A node in a phylogeny.

    Attributes
    ----------
    id:
        Tree-unique integer assigned by :meth:`makeyourtree.core.tree.Tree.new_node`.
        Stable for the lifetime of the node; used as the key in layout frames,
        style maps and annotation tables.
    name:
        Taxon label for leaves; an optional clade label for internal nodes.
    branch_length:
        Length of the edge *parent -> self*, or ``None`` when the file gave none.
    support:
        Branch support for the edge *parent -> self* (bootstrap, posterior, ...).
        ``None`` when absent.  See :mod:`makeyourtree.io` for how the classic
        internal-label / support ambiguity is resolved.
    attrs:
        Free-form per-node metadata: NHX key/values, NEXUS ``[&k=v]`` comment
        fields, PhyloXML taxonomy and sequence data, and user columns.  Never
        used by the layout engine; available to tracks and the inspector panel.
    comment:
        Verbatim comment text, preserved for round-tripping.
    style:
        Per-node style overrides (see :mod:`makeyourtree.style`).  ``None`` means
        "inherit everything".  Keys are field names of
        :class:`~makeyourtree.style.theme.NodeStyle`.
    collapsed:
        When true the subtree is drawn as a single summary shape and its
        descendants occupy no rows.
    hidden:
        When true the node and its subtree are excluded from layout entirely.

    Derived attributes
    ------------------
    ``n_leaves``, ``height``, ``depth_len``, ``level``, ``span_lo``, ``span_hi``
    are caches recomputed by :meth:`makeyourtree.core.tree.Tree.refresh`.  Treat them
    as read-only outside the core; they are meaningless until ``refresh`` has run.
    """

    __slots__ = (
        "id", "name", "branch_length", "support", "attrs", "comment",
        "parent", "children", "style", "collapsed", "hidden",
        # derived caches -- written by Tree.refresh()
        "n_leaves", "height", "depth_len", "level", "span_lo", "span_hi",
    )

    def __init__(
        self,
        name: str | None = None,
        branch_length: float | None = None,
        support: float | None = None,
        *,
        id: int = -1,
        parent: "Node | None" = None,
        attrs: dict[str, Any] | None = None,
        comment: str | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.branch_length = branch_length
        self.support = support
        self.attrs: dict[str, Any] = attrs if attrs is not None else {}
        self.comment = comment
        self.parent: Node | None = parent
        self.children: list[Node] = []
        self.style: dict[str, Any] | None = None
        self.collapsed = False
        self.hidden = False
        # derived
        self.n_leaves = 1
        self.height = 0
        self.depth_len = 0.0
        self.level = 0
        self.span_lo = 0.0
        self.span_hi = 1.0

    # ------------------------------------------------------------------ shape

    @property
    def is_leaf(self) -> bool:
        """True when the node has no children at all (topological leaf)."""
        return not self.children

    @property
    def is_root(self) -> bool:
        return self.parent is None

    @property
    def is_tip(self) -> bool:
        """True when the node terminates the *visible* tree: a real leaf, or a
        collapsed clade, which occupies leaf-like rows in every layout."""
        return not self.children or self.collapsed

    @property
    def degree(self) -> int:
        """Incident edge count, including the parent edge. Used by unrooted layout."""
        return len(self.children) + (0 if self.parent is None else 1)

    def edge_length(self, default: float = 0.0) -> float:
        """Branch length as a number, substituting *default* when unset."""
        return default if self.branch_length is None else self.branch_length

    # ----------------------------------------------------------------- edits
    # Structural primitives.  They do NOT refresh derived caches and do NOT
    # register undo entries -- use makeyourtree.ops for user-facing edits.

    def add_child(self, child: "Node", index: int | None = None) -> "Node":
        if child is self:
            raise ValueError("a node cannot be its own child")
        if child.parent is not None:
            child.parent.remove_child(child)
        child.parent = self
        if index is None:
            self.children.append(child)
        else:
            self.children.insert(index, child)
        return child

    def remove_child(self, child: "Node") -> "Node":
        try:
            self.children.remove(child)
        except ValueError:
            raise ValueError(f"{child!r} is not a child of {self!r}") from None
        child.parent = None
        return child

    def detach(self) -> "Node":
        """Remove this node, with its subtree, from its parent and return it."""
        if self.parent is not None:
            self.parent.remove_child(self)
        return self

    def replace_child(self, old: "Node", new: "Node") -> None:
        i = self.children.index(old)
        old.parent = None
        if new.parent is not None:
            new.parent.remove_child(new)
        new.parent = self
        self.children[i] = new

    def child_index(self) -> int:
        """Position of this node within the child list of its parent."""
        if self.parent is None:
            return 0
        return self.parent.children.index(self)

    # ------------------------------------------------------------- traversal
    # Convenience wrappers.  The canonical iterative implementations live in
    # makeyourtree.core.traversal and are what performance-sensitive code uses.

    def iter_ancestors(self, include_self: bool = False) -> Iterator["Node"]:
        n = self if include_self else self.parent
        while n is not None:
            yield n
            n = n.parent

    def path_to_root(self, include_self: bool = True) -> list["Node"]:
        return list(self.iter_ancestors(include_self=include_self))

    # ---------------------------------------------------------------- styling

    def set_style(self, **kw: Any) -> None:
        """Merge style overrides into this node; keys passed as ``None`` are cleared."""
        if self.style is None:
            self.style = {}
        for k, v in kw.items():
            if v is None:
                self.style.pop(k, None)
            else:
                self.style[k] = v
        if not self.style:
            self.style = None

    def clear_style(self) -> None:
        self.style = None

    # ------------------------------------------------------------------ misc

    def shallow_copy(self) -> "Node":
        """Copy this node's own data, without parent or children links."""
        n = Node(self.name, self.branch_length, self.support, id=self.id,
                 attrs=dict(self.attrs), comment=self.comment)
        n.style = None if self.style is None else dict(self.style)
        n.collapsed = self.collapsed
        n.hidden = self.hidden
        return n

    def __repr__(self) -> str:
        kind = "leaf" if self.is_leaf else f"clade[{len(self.children)}]"
        nm = f" {self.name!r}" if self.name else ""
        bl = "" if self.branch_length is None else f" bl={self.branch_length:g}"
        return f"<Node#{self.id} {kind}{nm}{bl}>"

# SPDX-License-Identifier: MIT
"""Iterative tree traversals.

Every traversal here is iterative on purpose.  A pectinate ("caterpillar") tree
of 100 000 leaves has a path length of 100 000, and CPython's default recursion
limit is 1000, so any recursive walk crashes on exactly the inputs users care
most about.  These generators allocate one list and never recurse.

Visibility
----------
All traversals accept ``visible_only``.  When true:

* nodes with ``hidden`` set are skipped along with their entire subtree, and
* nodes with ``collapsed`` set are yielded but **not descended into**.

That makes a collapsed clade behave exactly like a leaf, which is what the
layout engine, the row allocator and hit-testing all want.
"""

from __future__ import annotations

from typing import Iterator, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .node import Node

__all__ = [
    "preorder", "postorder", "levelorder", "iter_leaves", "iter_tips",
    "iter_internal", "iter_edges", "descend",
]


def descend(node: "Node", visible_only: bool = False) -> list["Node"]:
    """Children to walk into from *node* under the current visibility rule."""
    if not visible_only:
        return node.children
    if node.collapsed:
        return []
    return [c for c in node.children if not c.hidden]


def preorder(node: "Node", visible_only: bool = False) -> Iterator["Node"]:
    """Parents before children.  Children in declared left-to-right order."""
    if visible_only and node.hidden:
        return
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        kids = descend(n, visible_only)
        for c in reversed(kids):
            stack.append(c)


def postorder(node: "Node", visible_only: bool = False) -> Iterator["Node"]:
    """Children before parents.  Children in declared left-to-right order.

    This is the workhorse: leaf-row assignment, subtree size accumulation and
    every bottom-up statistic uses it.
    """
    if visible_only and node.hidden:
        return
    # Two-stack formulation: push-reversed-preorder, then drain.
    out: list[Node] = []
    stack = [node]
    while stack:
        n = stack.pop()
        out.append(n)
        for c in descend(n, visible_only):
            stack.append(c)
    for n in reversed(out):
        yield n


def levelorder(node: "Node", visible_only: bool = False) -> Iterator["Node"]:
    """Breadth-first, shallowest node first."""
    if visible_only and node.hidden:
        return
    from collections import deque
    q = deque([node])
    while q:
        n = q.popleft()
        yield n
        q.extend(descend(n, visible_only))


def iter_leaves(node: "Node", visible_only: bool = False) -> Iterator["Node"]:
    """Topological leaves, left to right.

    With ``visible_only`` this yields *tips* -- real leaves plus collapsed
    clades -- because those are the entities that occupy rows.
    """
    for n in preorder(node, visible_only):
        if visible_only:
            if n.collapsed or not descend(n, True):
                yield n
        elif not n.children:
            yield n


def iter_tips(node: "Node") -> Iterator["Node"]:
    """Alias for ``iter_leaves(node, visible_only=True)``; reads better at call sites."""
    return iter_leaves(node, visible_only=True)


def iter_internal(node: "Node", visible_only: bool = False) -> Iterator["Node"]:
    """Nodes that have at least one child under the current visibility rule."""
    for n in preorder(node, visible_only):
        if descend(n, visible_only):
            yield n


def iter_edges(node: "Node", visible_only: bool = False) -> Iterator[tuple["Node", "Node"]]:
    """Yield ``(parent, child)`` for every visible edge, parents first."""
    for n in preorder(node, visible_only):
        for c in descend(n, visible_only):
            yield n, c

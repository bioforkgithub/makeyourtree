# SPDX-License-Identifier: MIT
"""Fixtures and comparison utilities for the tree-operation tests.

The Newick writer here is deliberately local rather than imported from
:mod:`makeyourtree.io`: these tests check ``ops`` and must not fail because a parser
is mid-flight.  It is also stricter than a normal writer -- it can emit node ids
and supports -- because the undo tests need a string that changes if *anything*
about the tree changes, not just its topology.
"""

from __future__ import annotations

import random
from typing import Iterable

from makeyourtree.core.node import Node
from makeyourtree.core.traversal import iter_leaves, postorder, preorder
from makeyourtree.core.tree import Tree


def _num(x: float) -> str:
    return f"{x:.12g}"


def newick(tree: Tree, *, ids: bool = False, supports: bool = True) -> str:
    """Serialise a tree iteratively, from the leaves up.

    Not recursive: the caterpillar fixtures in this suite are deeper than the
    interpreter's recursion limit.
    """
    parts: dict[int, str] = {}
    for n in postorder(tree.root):
        label = n.name or ""
        if ids:
            label += f"#{n.id}"
        if supports and n.support is not None:
            label += f"[{_num(n.support)}]"
        if n.branch_length is not None:
            label += f":{_num(n.branch_length)}"
        if n.children:
            inner = ",".join(parts.pop(id(c)) for c in n.children)
            parts[id(n)] = f"({inner}){label}"
        else:
            parts[id(n)] = label
    return parts[id(tree.root)] + ";"


def signature(tree: Tree) -> str:
    """Everything an undo has to restore: shape, names, ids, lengths, supports,
    collapse flags and the rooted flag."""
    flags = ",".join(f"{n.id}" for n in preorder(tree.root) if n.collapsed)
    return f"{newick(tree, ids=True)}|rooted={tree.rooted}|collapsed={flags}"


def leaf_names(tree: Tree) -> list[str]:
    return [lf.name or f"#{lf.id}" for lf in iter_leaves(tree.root)]


def total_length(tree: Tree) -> float:
    return sum(n.edge_length(0.0) for n in preorder(tree.root) if n is not tree.root)


def pairwise_distances(tree: Tree) -> dict[tuple[str, str], float]:
    """Patristic distance between every pair of leaves, keyed by sorted name pair."""
    leaves = list(iter_leaves(tree.root))
    out: dict[tuple[str, str], float] = {}
    for i, a in enumerate(leaves):
        for b in leaves[i + 1:]:
            key = tuple(sorted((a.name or f"#{a.id}", b.name or f"#{b.id}")))
            out[key] = tree.distance(a, b)  # type: ignore[index]
    return out


def bipartitions(tree: Tree) -> dict[frozenset[str], set[float]]:
    """Map every edge's split to the support values recorded for it.

    A split is canonicalised by dropping the half that contains the alphabetically
    first taxon, so the same split has the same key however the tree is rooted --
    which is the point: rerooting must not move a support value to another split.
    The value is a set because rerooting legitimately duplicates one support (the
    edge it splits in two) and legitimately fuses two identical ones.
    """
    names = set(leaf_names(tree))
    pivot = min(names)
    below: dict[int, frozenset[str]] = {}
    out: dict[frozenset[str], set[float]] = {}
    for n in postorder(tree.root):
        if not n.children:
            below[id(n)] = frozenset({n.name or f"#{n.id}"})
        else:
            acc: set[str] = set()
            for c in n.children:
                acc |= below[id(c)]
            below[id(n)] = frozenset(acc)
        if n is tree.root or n.support is None:
            continue
        side = below[id(n)]
        key = frozenset(names - side) if pivot in side else side
        out.setdefault(key, set()).add(n.support)
    return out


def _apply_token(node: Node, token: str) -> None:
    label = token
    if ":" in token:
        label, _, length = token.partition(":")
        node.branch_length = float(length) if length else None
    if "[" in label:
        label, _, sup = label.partition("[")
        node.support = float(sup.rstrip("]"))
    if label:
        node.name = label


def build(text: str) -> Tree:
    """Parse a small hand-written Newick fixture: ``((a:1,b:2)[90]:3,c:4);``.

    Iterative, and deliberately minimal -- it exists so the fixtures in these tests
    read as trees rather than as twenty lines of ``add_child``.  Support goes in
    square brackets so that an internal label is never mistaken for one.
    """
    s = text.strip().rstrip(";")
    stack: list[Node] = []
    node: Node | None = None
    root: Node | None = None
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "(":
            n = Node()
            if stack:
                stack[-1].add_child(n)
            else:
                root = n
            stack.append(n)
            node = None
            i += 1
        elif ch == ",":
            node = None
            i += 1
        elif ch == ")":
            node = stack.pop()
            i += 1
        else:
            j = i
            while j < len(s) and s[j] not in "(),":
                j += 1
            if node is None:
                node = Node()
                if stack:
                    stack[-1].add_child(node)
                else:
                    root = node
            _apply_token(node, s[i:j])
            i = j
    assert root is not None and not stack, f"unbalanced fixture: {text!r}"
    tree = Tree(root)
    tree.refresh()
    return tree


def random_tree(n_leaves: int, seed: int = 0, *, root_degree: int = 2,
                with_support: bool = True, prefix: str = "t") -> Tree:
    """A random bifurcating tree with distinct lengths and distinct supports.

    Distinctness is what makes the reroot tests meaningful: with repeated values a
    length or support that migrated to the neighbouring edge would still compare
    equal.  ``root_degree=3`` produces a topologically unrooted tree, where every
    edge stands for a different bipartition -- the clean case for the support test.
    """
    rng = random.Random(seed)
    pool: list[Node] = [Node(name=f"{prefix}{i}") for i in range(n_leaves)]
    for lf in pool:
        lf.branch_length = round(rng.uniform(0.05, 2.0), 6)
    while len(pool) > root_degree:
        a = pool.pop(rng.randrange(len(pool)))
        b = pool.pop(rng.randrange(len(pool)))
        p = Node(branch_length=round(rng.uniform(0.05, 2.0), 6))
        p.add_child(a)
        p.add_child(b)
        pool.append(p)
    root = Node()
    for c in pool:
        root.add_child(c)
    tree = Tree(root)

    if with_support:
        values = iter(range(1, 10_000))
        if root_degree == 2:
            # The two edges below a bifurcating root describe the same split, so
            # they must carry the same number or the fixture itself is inconsistent.
            shared = float(next(values))
            for c in root.children:
                c.support = shared
        for n in preorder(root):
            if n is root or not n.children:
                continue
            if root_degree == 2 and n.parent is root:
                continue
            n.support = float(next(values))
    tree.refresh()
    return tree


def caterpillar(n_leaves: int, *, length: float = 1.0) -> Tree:
    """A fully pectinate tree: depth grows with the leaf count.

    This is the shape that breaks recursive implementations, so the scaling tests
    use it rather than a balanced tree.
    """
    root = Node()
    cur = root
    for i in range(n_leaves - 1):
        cur.add_child(Node(name=f"c{i}", branch_length=length))
        nxt = Node(branch_length=length)
        cur.add_child(nxt)
        cur = nxt
    cur.name = f"c{n_leaves - 1}"
    return Tree(root)


def names_of(nodes: Iterable[Node]) -> list[str]:
    return [n.name or f"#{n.id}" for n in nodes]

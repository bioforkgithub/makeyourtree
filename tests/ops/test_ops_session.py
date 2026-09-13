# SPDX-License-Identifier: MIT
"""A scripted editing session, driven through :class:`CommandStack`.

This is the test that catches undo state a single-operation test misses: the
commands interleave, so a reroot has to undo correctly on a tree that a prune and
three rotations have since rewritten, and back again.  A hundred operations then
a hundred undos must land on the original tree byte for byte -- ids included.
"""

from __future__ import annotations

import random

import pytest

from makeyourtree.core.errors import OperationError
from makeyourtree.ops import (CommandStack, collapse, delete_node, expand,
                          ladderize, midpoint_root, outgroup_root, prune,
                          rename, reroot_on_edge, rotate, sort_children,
                          unroot)

from _ops_helpers import random_tree, signature

N_OPERATIONS = 100


def _pick(rng, seq):
    return seq[rng.randrange(len(seq))] if seq else None


def _propose(rng, tree):
    """Build one random command against the tree's current state, or None.

    Every operation is offered a target chosen from the tree as it is *now*, which
    is the point of the exercise: a command built against a stale node would be
    testing nothing.
    """
    kind = rng.choice(["reroot", "midpoint", "outgroup", "unroot", "ladderize",
                       "rotate", "sort", "collapse", "expand", "rename",
                       "prune", "delete"])
    nodes = tree.nodes
    internals = [n for n in nodes if n.children]
    leaves = [n for n in nodes if not n.children]
    rerootable = [n for n in nodes if n.parent is not None]

    if kind == "reroot":
        target = _pick(rng, rerootable)
        return reroot_on_edge(tree, target, rng.uniform(0.0, target.edge_length()))
    if kind == "midpoint":
        return midpoint_root(tree)
    if kind == "outgroup":
        clade = _pick(rng, [n for n in internals if n.parent is not None])
        return None if clade is None else outgroup_root(tree, [clade],
                                                        at_fraction=rng.random())
    if kind == "unroot":
        return unroot(tree)
    if kind == "ladderize":
        return ladderize(tree, ascending=rng.random() < 0.5,
                         key=rng.choice(["size", "depth", "len", "name"]))
    if kind == "rotate":
        node = _pick(rng, [n for n in internals if len(n.children) > 1])
        return None if node is None else rotate(tree, node)
    if kind == "sort":
        node = _pick(rng, [n for n in internals if len(n.children) > 1])
        return None if node is None else sort_children(
            tree, node, rng.choice(["size", "name"]), rng.random() < 0.5)
    if kind == "collapse":
        node = _pick(rng, internals)
        return None if node is tree.root else collapse(tree, node)
    if kind == "expand":
        node = _pick(rng, [n for n in internals if n.collapsed])
        return None if node is None else expand(tree, node)
    if kind == "rename":
        node = _pick(rng, nodes)
        return rename(tree, node, f"r{rng.randrange(1000)}")
    if kind == "prune":
        if len(leaves) <= 4:
            return None
        victims = rng.sample(leaves, k=min(2, len(leaves) - 3))
        return prune(tree, victims)
    node = _pick(rng, [n for n in internals if n.parent is not None])
    return None if node is None else delete_node(tree, node)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 17])
def test_a_hundred_operations_fully_undone_restore_the_original(seed):
    rng = random.Random(seed)
    tree = random_tree(40, seed=seed)
    original = signature(tree)
    stack = CommandStack(tree, limit=10_000)

    applied = 0
    attempts = 0
    while applied < N_OPERATIONS and attempts < N_OPERATIONS * 6:
        attempts += 1
        try:
            cmd = _propose(rng, tree)
        except OperationError:
            continue
        if cmd is None:
            continue
        try:
            stack.do(cmd)
        except OperationError:
            # A refused edit must not have half-applied itself.
            assert stack.can_undo or signature(tree) == original
            continue
        applied += 1

    assert applied == N_OPERATIONS, "the session did not reach a hundred edits"
    assert signature(tree) != original
    assert len(stack.history()) == N_OPERATIONS

    while stack.can_undo:
        stack.undo()
    assert signature(tree) == original
    assert not stack.can_undo
    assert stack.can_redo


@pytest.mark.parametrize("seed", [0, 5])
def test_undo_then_redo_returns_to_the_edited_tree(seed):
    rng = random.Random(seed)
    tree = random_tree(30, seed=seed)
    stack = CommandStack(tree, limit=10_000)
    applied = 0
    while applied < 40:
        cmd = _propose(rng, tree)
        if cmd is None:
            continue
        try:
            stack.do(cmd)
        except OperationError:
            continue
        applied += 1

    edited = signature(tree)
    while stack.can_undo:
        stack.undo()
    while stack.can_redo:
        stack.redo()
    assert signature(tree) == edited


def test_the_stack_reports_dirtiness_and_labels():
    tree = random_tree(8, seed=1)
    stack = CommandStack(tree)
    assert not stack.is_dirty
    stack.do(rotate(tree, tree.root))
    assert stack.is_dirty
    assert stack.undo_label is not None
    stack.undo()
    assert not stack.is_dirty

# SPDX-License-Identifier: MIT
"""Fixtures for the group-A track suite.  The machinery lives in
:mod:`helpers`, which the test modules import directly."""

from __future__ import annotations

import pytest

from helpers import MODES, make_context, make_tree
from makeyourtree.core.tree import Tree
from makeyourtree.layout.params import LayoutMode
from makeyourtree.tracks.base import TrackContext


@pytest.fixture
def tree() -> Tree:
    return make_tree(8)


@pytest.fixture(params=MODES, ids=[m.value for m in MODES])
def mode(request) -> LayoutMode:
    return request.param


@pytest.fixture
def ctx(tree: Tree, mode: LayoutMode) -> TrackContext:
    return make_context(tree, mode)


@pytest.fixture
def rect_ctx(tree: Tree) -> TrackContext:
    return make_context(tree, LayoutMode.RECTANGULAR)

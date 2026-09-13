# SPDX-License-Identifier: MIT
"""Fixtures for the chart-shaped annotation tracks.

The scaffolding itself lives in :mod:`_support`, which also installs stand-ins
for the sibling modules this unit's neighbours have not written yet; importing
it first is what makes ``import makeyourtree.tracks`` work in a partial checkout.
"""

from __future__ import annotations

import pytest

from _support import (ROOTED_MODES, LayoutMode, Scene, Tree, build_frame,
                      build_tree, make_context)


@pytest.fixture(params=[m.value for m in ROOTED_MODES],
                ids=[m.value for m in ROOTED_MODES])
def mode(request) -> LayoutMode:
    return LayoutMode(request.param)


@pytest.fixture
def tree() -> Tree:
    return build_tree()


@pytest.fixture
def context_for():
    """Factory: ``context_for(tree, mode, offset=...)`` -> a drawable context."""
    return make_context


@pytest.fixture
def scene() -> Scene:
    return Scene(width=900.0, height=600.0)


@pytest.fixture
def frame_for():
    """Factory: ``frame_for(tree, mode)`` -> a hand-built layout frame."""
    return build_frame

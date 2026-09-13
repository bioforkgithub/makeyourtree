# SPDX-License-Identifier: MIT
"""Fixtures for the annotation and project-file tests.

The helpers themselves live in :mod:`_annot_support` rather than here.  pytest's
default (prepend) import mode puts each test directory on ``sys.path`` and
caches modules under their bare name, so three directories each holding a
``conftest.py`` that test modules import from by name compete for the single
``sys.modules["conftest"]`` slot: whichever is collected first wins and the
others fail with ImportError.  The full suite only happened to survive because
alphabetical order put the winner first -- running any subset in another order
broke collection.  A uniquely named module cannot collide, so shared helpers
live there and only pytest-discovered fixtures stay in this file.
"""

from __future__ import annotations

import pytest

from makeyourtree.core.tree import Tree
from makeyourtree.tracks import base as track_base
from _annot_support import ProbeTrack


@pytest.fixture(autouse=True)
def probe_track():
    """Register :class:`ProbeTrack` for the duration of one test.

    The registry is global, so the registration is undone afterwards rather
    than left to leak into another unit's view of
    :func:`makeyourtree.tracks.base.track_types`.
    """
    registry = track_base._REGISTRY
    before = registry.get(ProbeTrack.type_id)
    if before is not ProbeTrack:
        track_base.register(ProbeTrack)
    yield ProbeTrack
    if before is None:
        registry.pop(ProbeTrack.type_id, None)


@pytest.fixture
def tree() -> Tree:
    """``((A,B)AB,(C,D)CD)root;`` with branch lengths and stable ids."""
    t = Tree()
    root = t.root
    root.name = "root"
    for clade_name, leaf_names in (("AB", ("A", "B")), ("CD", ("C", "D"))):
        clade = t.new_node(clade_name, 0.5)
        root.add_child(clade)
        for leaf in leaf_names:
            clade.add_child(t.new_node(leaf, 0.25))
    t.refresh()
    return t

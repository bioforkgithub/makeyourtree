# SPDX-License-Identifier: MIT
"""Fixtures for the compositor, legend, backend and CLI tests.

The helpers themselves live in :mod:`_render_support` rather than here.  pytest's
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
from makeyourtree.doc.document import Document
from _render_support import RecordingBackend, build_tree, make_document


@pytest.fixture
def tree() -> Tree:
    return build_tree()


@pytest.fixture
def document(tree: Tree) -> Document:
    return make_document(tree)


@pytest.fixture
def recorder() -> RecordingBackend:
    return RecordingBackend()

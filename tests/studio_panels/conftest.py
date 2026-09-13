# SPDX-License-Identifier: MIT
"""Fixtures for the dock-panel tests.

One ``QApplication`` for the whole run. Qt permits exactly one per process and
destroying it mid-run tears down every widget still alive, so the fixture reuses
whatever instance already exists rather than creating a second.

Nothing here asserts on rendered text. The offscreen platform reports zero font
families, so glyph metrics are meaningless; every assertion in this directory is
about structure, counts and state.
"""

from __future__ import annotations

import pytest

from makeyourtree.doc.document import Document
from makeyourtree_studio.session import Session

from _panels_support import sample_document, sample_tree


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    created = app is None
    if created:
        app = QApplication([])
    yield app


@pytest.fixture
def tree(qapp):
    return sample_tree()


@pytest.fixture
def document(qapp):
    return sample_document()


@pytest.fixture
def studio(qapp, document: Document) -> Session:
    """A session over the sample document, with no widgets attached yet."""
    return Session(document)

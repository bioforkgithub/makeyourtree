# SPDX-License-Identifier: MIT
"""Fixtures for the canvas suite.

Every test here needs a live ``QApplication`` -- ``QFontMetricsF``, ``QPainter``
and ``QGraphicsScene`` all assume one exists -- so it is created once for the
whole session and never torn down; destroying and rebuilding it between tests is
a well known source of crashes on the offscreen platform.
"""

from __future__ import annotations

import pytest

from PySide6.QtWidgets import QApplication

from canvas_helpers import make_session

from makeyourtree_studio.session import Session


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def session(qapp: QApplication) -> Session:
    return make_session()


@pytest.fixture
def canvas(session: Session):
    from makeyourtree_studio.canvas.view import TreeCanvas

    view = TreeCanvas(session)
    view.resize(800, 600)
    return view

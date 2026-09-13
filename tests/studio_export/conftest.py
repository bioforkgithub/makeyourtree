# SPDX-License-Identifier: MIT
"""Fixtures for the export and dialog tests.

Everything runs on the offscreen platform, which reports **zero font families**,
so nothing here asserts on rendered glyphs -- only on geometry, structure and
file-level facts.

``QSettings`` is redirected to a temporary INI tree for the whole session. The
export dialog remembers the user's last choices, and a test suite that wrote
those into the real registry or the real config directory would both leak state
between runs and vandalise the developer's own preferences.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from makeyourtree.core.tree import Tree  # noqa: E402
from makeyourtree.doc.document import Document  # noqa: E402
from makeyourtree.scene.marks import (Anchor, LinesMark, Paint, RectMark,  # noqa: E402
                                  Scene, TextMark, TextStyle)
from makeyourtree.style.color import Color  # noqa: E402
from makeyourtree_studio.session import Session  # noqa: E402

NEWICK = ("(((alpha:0.1,beta:0.2)ab:0.3,(gamma:0.15,delta:0.25)gd:0.2)abgd:0.1,"
          "(epsilon:0.4,zeta:0.35)ez:0.2);")
"""Six named tips, synthetic. Enough structure for a layout with real extent."""


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(scope="session", autouse=True)
def _isolated_settings(tmp_path_factory):
    """Point QSettings at a throwaway INI tree for the whole test session."""
    root = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(root))
    yield root


@pytest.fixture
def scene() -> Scene:
    """A hand-built scene with a known, exact size.

    Built directly rather than through ``compose`` so the raster tests measure
    the exporters and nothing else; a change in layout maths must not be able to
    make a pixel-dimension assertion fail.
    """
    s = Scene(width=320.0, height=240.0, background=Color(250, 250, 252))
    s.add(RectMark(paint=Paint(fill=Color(220, 226, 240),
                               stroke=Color(40, 40, 60), width=1.5),
                   x=20.0, y=20.0, w=120.0, h=80.0))
    s.add(LinesMark(paint=Paint(stroke=Color(30, 30, 40), width=2.0),
                    coords=(20.0, 140.0, 300.0, 140.0,
                            20.0, 160.0, 300.0, 160.0,
                            20.0, 180.0, 300.0, 180.0)))
    s.add(TextMark(x=20.0, y=210.0, text="alpha",
                   style=TextStyle(size=12.0, anchor=Anchor.START)))
    return s


@pytest.fixture
def fractional_scene() -> Scene:
    """A scene whose size is not a whole number, to catch rounding drift."""
    return Scene(width=92.22, height=109.61, background=Color(255, 255, 255))


@pytest.fixture
def tree() -> Tree:
    return Tree.from_newick(NEWICK)


@pytest.fixture
def session(qapp, tree) -> Session:
    return Session(Document(tree=tree))

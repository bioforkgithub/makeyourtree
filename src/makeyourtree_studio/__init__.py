# SPDX-License-Identifier: MIT
"""MakeYourTree Studio — the desktop application built on the ``makeyourtree`` core.

Nothing is imported eagerly here. Importing this package must not pull in Qt:
``makeyourtree_studio.packaging`` is read by the build driver, and the settings
façade is read by scripted exports, neither of which wants a ``QApplication``
brought into existence as a side effect of a top-level import.

The application entry point is :func:`makeyourtree_studio.app.main`; ``python -m
makeyourtree_studio`` runs it.
"""

from __future__ import annotations

from makeyourtree import __version__

__all__ = ["__version__"]

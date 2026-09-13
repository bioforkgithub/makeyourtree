# SPDX-License-Identifier: MIT
"""Entry script for the frozen application.

PyInstaller executes its entry script as ``__main__``, with no package context.
That rules out pointing the spec at ``src/makeyourtree_studio/app.py`` directly:
its relative imports (``from .canvas.qt_metrics import QtMetrics``) raise
``ImportError: attempted relative import with no known parent package`` before
a window is ever built. In a windowed build there is no console to print the
traceback to, so the only symptom is the process exiting with status 1 — which
is how this survived undetected until the first bundle was actually launched.

Reaching the application through an absolute import instead keeps
``makeyourtree_studio`` a real package at run time, so ``app`` is imported exactly
as it is in a source checkout and the two start-up paths cannot diverge.
"""

from __future__ import annotations

import sys

from makeyourtree_studio.app import main

if __name__ == "__main__":
    sys.exit(main())

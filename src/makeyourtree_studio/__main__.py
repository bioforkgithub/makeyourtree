# SPDX-License-Identifier: MIT
"""``python -m makeyourtree_studio`` — the same entry point as the packaged binary.

A module runner rather than a script so that a developer checkout and an
installed wheel start the application by exactly the same code path, and so the
PyInstaller bundle has one documented thing to invoke.
"""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())

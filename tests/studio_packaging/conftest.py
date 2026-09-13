# SPDX-License-Identifier: MIT
"""Fixtures for the packaging tests.

The bundle fixtures fabricate the *shape* of a PyInstaller ``--onedir`` output
rather than running PyInstaller, which takes minutes and needs a build toolchain.
What the verifier inspects is file layout and file names, so a directory tree of
empty files exercises exactly the logic that matters — and every failure mode
(missing licence text, embedded Qt, a GPL-only add-on) can be produced on demand
instead of hoping one occurs.

Helpers are exposed as fixtures rather than importable module attributes so the
test package needs no ``__init__.py`` and no cross-module imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

import pytest

#: The layout PyInstaller 6 produces: launcher at the top, everything else under
#: ``_internal/``.
_GOOD_BUNDLE_FILES: tuple[str, ...] = (
    "MakeYourTreeStudio.exe",
    "_internal/LICENSES/GPL-3.0.txt",
    "_internal/LICENSES/LGPL-3.0.txt",
    "_internal/LICENSES/MIT.txt",
    "_internal/THIRD-PARTY-NOTICES.md",
    "_internal/LICENSE.md",
    "_internal/Qt6Core.dll",
    "_internal/Qt6Gui.dll",
    "_internal/Qt6Widgets.dll",
    "_internal/PySide6/QtCore.pyd",
    "_internal/base_library.zip",
    "_internal/python312.dll",
)


@pytest.fixture
def bundle_files() -> tuple[str, ...]:
    """Paths, relative to the bundle root, of a distribution that should pass."""
    return _GOOD_BUNDLE_FILES


@pytest.fixture
def make_bundle(tmp_path: Path) -> Callable[[Sequence[str]], Path]:
    """Factory creating a bundle directory containing the given empty files."""

    def _make(relative_paths: Sequence[str], name: str = "MakeYourTreeStudio") -> Path:
        root = tmp_path / name
        for relative in relative_paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")
        return root

    return _make


@pytest.fixture
def good_bundle(make_bundle: Callable[[Sequence[str]], Path]) -> Path:
    """A bundle that should pass every verification check."""
    return make_bundle(_GOOD_BUNDLE_FILES)

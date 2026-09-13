# SPDX-License-Identifier: MIT
"""Licence and clean-room compliance, enforced by the build.

These are not style checks. Each one guards a condition that, if breached, either
voids the right to distribute Qt alongside our own code or weakens the clean-room
record. A reviewer cannot be relied on to catch a stray import; the build can.

See ``LICENSE.md`` for why each rule exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "makeyourtree"
STUDIO = ROOT / "src" / "makeyourtree_studio"

CORE_SPDX = "# SPDX-License-Identifier: MIT"
STUDIO_SPDX = "# SPDX-License-Identifier: MIT"

#: Qt add-ons that are GPL-3.0-only in the open-source edition. Linking any one of
#: them forces any distributed binary to GPL-3.0, which would strip the permissive
#: MIT terms this project exists to offer.
GPL_ONLY_QT_MODULES = (
    "QtCharts",
    "QtDataVisualization",
    "QtVirtualKeyboard",
)


def py_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------- core purity


def test_core_never_imports_a_gui_toolkit():
    """The MIT core must stay toolkit-free.

    This is what lets the core be used headlessly, tested in CI, embedded by third
    parties under MIT, and shipped separately from the LGPL-encumbered Qt runtime.
    A single PySide6 import in the core would entangle the MIT package with Qt.
    """
    pattern = re.compile(r"^\s*(?:from|import)\s+(PySide\d|PyQt\d)\b", re.MULTILINE)
    offenders = [
        str(p.relative_to(ROOT))
        for p in py_files(CORE)
        if pattern.search(read(p))
    ]
    assert not offenders, (
        "makeyourtree core must not import a GUI toolkit; offending files: "
        + ", ".join(offenders)
    )


def test_core_declares_no_qt_dependency():
    """PySide6 belongs in the optional ``studio`` extra, never in ``dependencies``."""
    pyproject = read(ROOT / "pyproject.toml")
    deps_block = pyproject.split("[project.optional-dependencies]")[0]
    assert "PySide6" not in deps_block, (
        "PySide6 must stay in the optional 'studio' extra so the MIT core installs "
        "without pulling in an LGPL runtime"
    )


# ------------------------------------------------------- GPL-only Qt modules


@pytest.mark.parametrize("module", GPL_ONLY_QT_MODULES)
def test_no_gpl_only_qt_module_is_imported(module: str):
    """Qt Charts, Qt Data Visualization and Qt Virtual Keyboard are GPL-3.0-only.

    Importing one would make every distributed binary a GPL-3.0 work, so recipients
    would lose the MIT terms the rest of MakeYourTree is offered under. Chart-like output
    is produced by our own track renderers instead; see ``makeyourtree.tracks``.
    """
    pattern = re.compile(rf"\b{module}\b")
    offenders = [
        str(p.relative_to(ROOT))
        for p in py_files(CORE) + py_files(STUDIO)
        if pattern.search(read(p))
    ]
    assert not offenders, (
        f"{module} is GPL-3.0-only and would force every distributed binary to GPL; "
        "offending files: " + ", ".join(offenders)
    )


# --------------------------------------------------------------- SPDX headers


def test_every_core_file_declares_the_mit_licence():
    missing = [
        str(p.relative_to(ROOT))
        for p in py_files(CORE)
        if CORE_SPDX not in read(p)[:400]
    ]
    assert not missing, (
        f"every file under src/makeyourtree/ needs '{CORE_SPDX}' in its header; "
        "missing in: " + ", ".join(missing)
    )


def test_every_studio_file_declares_the_mit_licence():
    missing = [
        str(p.relative_to(ROOT))
        for p in py_files(STUDIO)
        if STUDIO_SPDX not in read(p)[:400]
    ]
    assert not missing, (
        f"every file under src/makeyourtree_studio/ needs '{STUDIO_SPDX}' in its header; "
        "missing in: " + ", ".join(missing)
    )


# ------------------------------------------------------- required distribution files


def test_required_licence_files_are_present_and_verbatim():
    """LGPL-3.0 §4(b) requires shipping both licence texts with the combined work.

    LGPL-3.0 is drafted as GPL-3.0 plus additional permissions, so the GPL text is
    required too. Length checks catch the placeholder being left in by accident.
    """
    gpl = ROOT / "LICENSES" / "GPL-3.0.txt"
    lgpl = ROOT / "LICENSES" / "LGPL-3.0.txt"
    mit = ROOT / "LICENSES" / "MIT.txt"

    for path in (gpl, lgpl, mit):
        assert path.exists(), f"{path.name} must ship with every distribution"

    gpl_text = read(gpl)
    assert "GNU GENERAL PUBLIC LICENSE" in gpl_text
    assert len(gpl_text) > 30_000, "GPL-3.0.txt looks truncated or is still a placeholder"

    lgpl_text = read(lgpl)
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl_text
    assert len(lgpl_text) > 5_000, "LGPL-3.0.txt looks truncated or is still a placeholder"

    assert "MIT License" in read(mit)


def test_third_party_notices_cover_every_distributed_dependency():
    notices = read(ROOT / "THIRD-PARTY-NOTICES.md")
    for required in ("PySide6", "LGPL-3.0", "NumPy", "BSD-3-Clause", "Python"):
        assert required in notices, f"THIRD-PARTY-NOTICES.md must mention {required}"


def test_no_licence_adds_restrictions_over_the_lgpl():
    """LGPL-3.0 §4 forbids terms restricting reverse engineering for debugging
    modifications to the Library. MIT imposes no such term, so the condition holds by
    construction -- but only for as long as no proprietary agreement is reintroduced.
    This test fails if one reappears without the carve-out that used to make it lawful.
    """
    agreements = [
        p for p in (ROOT / "LICENSES").iterdir()
        if p.is_file() and "eula" in p.name.lower()
    ]
    for path in agreements:
        lowered = read(path).lower()
        assert "reverse engineer" in lowered and "prevails" in lowered, (
            f"{path.name} reintroduces an end-user agreement without the LGPL-3.0 §4 "
            "reverse-engineering carve-out; that would terminate the right to "
            "distribute Qt at all"
        )


# ------------------------------------------------------------ clean-room guard


def test_no_third_party_product_branding_in_source():
    """Clean-room guard: no other product's branding may appear in our source.

    Naming a module, class, option or CLI flag after another product's branding is
    one of the documented ways a clean-room defence gets weakened. Discussion of
    prior art belongs in the documentation and the legal record, which are listed
    as exempt below.
    """
    forbidden = re.compile(r"\bitol\b|interactive tree of life", re.IGNORECASE)
    offenders = []
    for p in py_files(CORE) + py_files(STUDIO):
        text = read(p)
        if forbidden.search(text):
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, (
        "third-party branding must not appear in source; related work belongs in "
        "README.md. Offending files: " + ", ".join(offenders)
    )


def test_the_licence_is_conveyed():
    """The MIT text and the Qt licences must be in the tree, not just claimed.

    ``LICENSE`` is what a reuser and GitHub's licence detector both read, and
    ``LICENSE.md`` is what records the LGPL conditions that bind anyone
    redistributing a compiled bundle. Neither is optional.
    """
    for name in ("LICENSE", "LICENSE.md", "THIRD-PARTY-NOTICES.md"):
        assert (ROOT / name).exists(), f"{name} must be conveyed with the software"
    assert "MIT License" in read(ROOT / "LICENSE")

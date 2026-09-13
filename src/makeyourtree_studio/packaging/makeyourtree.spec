# SPDX-License-Identifier: MIT
# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for MakeYourTree Studio.
#
# =============================================================================
# READ BEFORE CHANGING ANYTHING IN THIS FILE. IT IS LICENCE-CRITICAL.
# =============================================================================
#
# ONEDIR ONLY. NEVER --onefile. NEVER STATIC LINKING.
#
# Qt is distributed under LGPL-3.0. LGPL-3.0 section 4(d)(1) lets us ship a
# proprietary application that uses Qt only if we "use a suitable shared library
# mechanism for linking with the Library ... that (a) uses at run time a copy of
# the Library already present on the user's computer system, ... or (b) will
# operate properly with a modified version of the Library that is
# interface-compatible with the Linked Version."
#
# A --onedir build satisfies that: Qt ships as separate, dynamically loaded
# .dll / .so / .dylib files that the user can overwrite with their own
# interface-compatible build of Qt, and the application will then load theirs.
#
# A --onefile build does NOT satisfy it. It packs the Qt shared libraries inside
# the executable and unpacks them to a temporary directory at every launch, so
# there is nothing a user can replace. Switching this spec to --onefile would
# leave us distributing Qt with no valid licence at all, which is copyright
# infringement, not a packaging preference. The only lawful alternatives are
# section 4(d)(0) (ship relinkable object code plus the complete Qt source) or
# buying a commercial Qt licence from The Qt Company.
#
# So: do not merge the binaries into the EXE, do not delete the COLLECT step,
# and do not "optimise" this into a single file. See LICENSE.md.
#
# Two more conditions this spec holds to:
#   * Qt ships UNMODIFIED — strip=False and upx=False everywhere. Stripping or
#     UPX-packing the Qt libraries produces a modified Qt, and modifications to
#     an LGPL library must themselves be published under the LGPL.
#   * The licence texts travel with the binary — see DATAS below. LGPL-3.0
#     4(a)/4(b)/4(c) require the notices and the full GPL and LGPL texts to be
#     present in the distribution and reachable at runtime, which is what the
#     Help > Third-Party Licences dialog reads.

import sys
from pathlib import Path

# ----------------------------------------------------------------- locations

# PyInstaller injects SPECPATH when it executes a spec; the fallback keeps the
# file importable by the test suite and by build.py, which parse it statically.
try:
    SPEC_DIR = Path(SPECPATH)  # noqa: F821 - injected by PyInstaller
except NameError:
    SPEC_DIR = Path(__file__).resolve().parent

# src/makeyourtree_studio/packaging -> src/makeyourtree_studio -> src -> repository root
PROJECT_ROOT = SPEC_DIR.parents[2]

APP_NAME = "MakeYourTreeStudio"
# The launcher, not app.py. PyInstaller runs the entry script as __main__ with
# no package context, so app.py's relative imports would fail at start-up; see
# launcher.py. The bundle exits with status 1 and no message if this regresses.
ENTRY_SCRIPT = SPEC_DIR / "launcher.py"


# --------------------------------------------------- GPL-only Qt add-on guard

# These Qt add-ons are GPL-3.0-only in the open-source Qt edition. Linking any
# one of them would relicense the whole of MakeYourTree Studio under GPL-3.0 and
# destroy the commercial licence. We import none of them, but an add-on can also
# arrive through a transitive hidden import or through the PySide6 hook
# collecting a whole plugin directory, so they are excluded explicitly here AND
# filtered out of the collected binaries below.
GPL_ONLY_QT_MODULES = (
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtVirtualKeyboard",
)

# Spelled out in full rather than built by concatenation so that build.py and
# tests/studio_packaging can read this list statically, without executing the
# spec. build.py additionally asserts GPL_ONLY_QT_MODULES is a subset of it.
EXCLUDES = [
    # GPL-3.0-only Qt add-ons. Never remove one of these.
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtVirtualKeyboard",
    # Test and tooling modules: a commercial bundle has no business shipping a
    # test runner, and dropping them keeps the distribution small.
    "pytest",
    "_pytest",
    "hypothesis",
    "tkinter",
    "IPython",
    "matplotlib",
    # Rival Qt bindings. If one is installed in the build environment, PySide6's
    # hooks can pick it up and ship two toolkits.
    "PyQt5",
    "PyQt6",
    "PySide2",
]


# --------------------------------------------------- imports PyInstaller misses

# PyInstaller collects what it can see being imported. Two things here are
# invisible to it, and both fail *silently* rather than loudly:
#
#   * Entry-point targets. The exporters and the figure inspector are looked up
#     through importlib.metadata at run time, so no import statement names them.
#     A missing one leaves the format "unavailable" or the "Read a published
#     figure" button disabled -- no traceback, just a feature that is not there.
#   * Deferred imports. main_window imports the guide dialog inside the handler
#     so that starting the application does not pay for a dialog most sessions
#     never open. Nothing imports it at module scope, so it is never collected,
#     and Help > Guide Me fails only when someone chooses it.
#
# Both were shipped broken once. Anything reachable only by name belongs here.
HIDDEN_IMPORTS = [
    "makeyourtree_studio.export.raster",
    "makeyourtree_studio.guide",
    "makeyourtree_studio.guide.inspect",
    "makeyourtree_studio.dialogs.guide_dialog",
    "PySide6.QtPdf",
]


# ------------------------------------------------------------- licence datas

# Every one of these must be present in the shipped bundle. LicensesDialog reads
# them at runtime from sys._MEIPASS, so the relative paths below are part of the
# runtime contract, not just tidiness: LICENSES/ stays LICENSES/, and the two
# top-level Markdown files stay at the top level.
REQUIRED_LICENCE_FILES = (
    ("LICENSES/GPL-3.0.txt", "LICENSES"),
    ("LICENSES/LGPL-3.0.txt", "LICENSES"),
    ("LICENSES/MIT.txt", "LICENSES"),
    ("THIRD-PARTY-NOTICES.md", "."),
    ("LICENSE.md", "."),
)


def _licence_datas():
    """(source, destination) pairs for every legal document we must ship.

    Fails the build rather than producing a bundle with a missing notice: an
    unnoticed omission here is a licence breach that ships to customers.
    """
    datas = []
    seen = set()
    for relative, dest in REQUIRED_LICENCE_FILES:
        source = PROJECT_ROOT / relative
        if not source.is_file():
            raise SystemExit(
                f"makeyourtree.spec: required licence file is missing: {source}. "
                "MakeYourTree Studio may not be distributed without it."
            )
        datas.append((str(source), dest))
        seen.add(source.resolve())
    # Anything else that has been added to LICENSES/ ships too, so a new
    # dependency's licence text cannot be left behind by forgetting this list.
    licenses_dir = PROJECT_ROOT / "LICENSES"
    if licenses_dir.is_dir():
        for extra in sorted(licenses_dir.iterdir()):
            if extra.is_file() and extra.resolve() not in seen:
                datas.append((str(extra), "LICENSES"))
    return datas


DATAS = _licence_datas()

# Package metadata, without which importlib.metadata finds no entry points.
#
# PyInstaller collects modules, not dist-info directories, so a frozen build has
# no record that this distribution advertises anything. Both optional features
# are discovered that way -- the raster exporters in
# makeyourtree.render.exporters and the figure inspector in
# makeyourtree.guide.figure -- and both degrade *silently*: the export falls
# back to "format unavailable" and the "Read a published figure" button simply
# arrives disabled. Nothing raises, so a build ships looking complete.
#
# Verified after a build by checking that _internal/ contains a
# makeyourtree-*.dist-info directory, and at run time by
# tests/studio_packaging/.
try:
    from PyInstaller.utils.hooks import copy_metadata
    DATAS += copy_metadata("makeyourtree")
except Exception as exc:  # pragma: no cover - only when PyInstaller is absent
    raise SystemExit(
        "makeyourtree.spec: cannot collect package metadata, without which the "
        f"optional exporters and the figure inspector go missing silently: {exc}")


def _without_gpl_only(entries):
    """Drop anything whose file name names a GPL-3.0-only Qt add-on.

    Belt and braces behind ``excludes``: PySide6's hooks can sweep in a whole
    directory of Qt libraries, and one stray Qt6Charts shared library inside the
    bundle is enough to make the distribution a GPL derivative work.
    """
    needles = []
    for dotted in GPL_ONLY_QT_MODULES:
        leaf = dotted.rsplit(".", 1)[-1]
        needles.append(leaf.lower())
        needles.append(("Qt6" + leaf[2:]).lower())
    kept = []
    for entry in entries:
        name = Path(str(entry[0])).name.lower()
        if any(needle in name for needle in needles):
            continue
        kept.append(entry)
    return kept


# ------------------------------------------------------------------ analysis

if not ENTRY_SCRIPT.is_file():
    raise SystemExit(f"makeyourtree.spec: entry script not found: {ENTRY_SCRIPT}")

a = Analysis(
    [str(ENTRY_SCRIPT)],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

a.binaries = _without_gpl_only(a.binaries)
a.datas = _without_gpl_only(a.datas)

pyz = PYZ(a.pure)

# exclude_binaries=True is what makes this a onedir build: the executable is a
# thin launcher and every shared library stays a separate, replaceable file
# beside it. Setting it to False, or passing the collected binaries here, turns
# this into a onefile bundle and breaks LGPL-3.0 4(d)(1). Do not.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# COLLECT writes the onedir tree: launcher, Qt shared libraries and licence
# files side by side, so a user can replace the Qt libraries in place.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

# On macOS the deliverable is an .app bundle, which is itself a directory tree:
# the Qt frameworks live in Contents/Frameworks as separate, replaceable files,
# so this keeps the onedir guarantee above rather than weakening it.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=APP_NAME + ".app",
        icon=None,
        bundle_identifier="studio.makeyourtree.MakeYourTreeStudio",
    )

# SPDX-License-Identifier: MIT
"""The PyInstaller spec is a licence document as much as a build script.

Every assertion here guards a condition that, if breached, means the shipped
product has no right to distribute Qt. They are written against the spec's *text*
and its parse tree rather than against ``build.py``'s helpers, so that a bug in
the verifier cannot make these pass.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "src" / "makeyourtree_studio" / "packaging" / "makeyourtree.spec"

#: GPL-3.0-only in the open-source Qt edition. Linking any one would make every
#: distributed binary a GPL-3.0 work, stripping the MIT terms we offer.
GPL_ONLY = ("PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtVirtualKeyboard")

#: Must reach the bundle for LGPL-3.0 4(a)/4(b)/4(c): the licence texts have to
#: be readable at runtime, which is what Help > Third-Party Licences does.
REQUIRED_IN_DATAS = (
    "LICENSES/GPL-3.0.txt",
    "LICENSES/LGPL-3.0.txt",
    "LICENSES/MIT.txt",
    "THIRD-PARTY-NOTICES.md",
    "LICENSE.md",
)


@pytest.fixture(scope="module")
def source() -> str:
    return SPEC.read_text(encoding="utf-8")


def call_arguments(source: str, func: str) -> str:
    """Text of the first top-level ``name = func(...)`` call, comments removed.

    Comments are stripped so an explanatory comment inside the call cannot make a
    structural assertion pass or fail by accident.
    """
    match = re.search(rf"^\s*\w+\s*=\s*{func}\(", source, re.MULTILINE)
    assert match is not None, f"the spec has no {func}(...) call"
    start = match.end()
    depth = 1
    for index in range(start, len(source)):
        if source[index] in "([{":
            depth += 1
        elif source[index] in ")]}":
            depth -= 1
            if depth == 0:
                body = source[start:index]
                return "\n".join(line.split("#", 1)[0] for line in body.splitlines())
    raise AssertionError(f"unbalanced brackets in the {func}(...) call")


def literal(source: str, name: str) -> object:
    module = ast.parse(source, filename=str(SPEC))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"the spec does not define {name} as a top-level literal")


# ------------------------------------------------------------------ existence


def test_spec_exists_and_is_valid_python(source: str) -> None:
    """A spec that will not parse fails the release build at the worst moment."""
    assert SPEC.is_file()
    ast.parse(source, filename=str(SPEC))


def test_spec_carries_the_commercial_spdx_header(source: str) -> None:
    assert source.startswith("# SPDX-License-Identifier: MIT")


# ----------------------------------------------------------- onedir semantics


def test_spec_collects_a_onedir_tree(source: str) -> None:
    """COLLECT is what writes the replaceable-shared-library tree.

    Without it the build is one-file and LGPL-3.0 4(d)(1) is not satisfied.
    """
    assert re.search(r"^\s*coll\s*=\s*COLLECT\(", source, re.MULTILINE), (
        "the spec must end in a COLLECT step; a spec with only an EXE step is a "
        "one-file build"
    )


def test_exe_does_not_bundle_the_binaries(source: str) -> None:
    """The one-file pattern is ``EXE(pyz, a.scripts, a.binaries, ..., a.datas)``.

    Passing the collected binaries to EXE embeds Qt in the executable, so a user
    can no longer replace it and our right to ship Qt lapses.
    """
    exe_args = call_arguments(source, "EXE")
    assert "a.binaries" not in exe_args, (
        "EXE must not receive the collected binaries: that is a one-file bundle"
    )
    assert "a.datas" not in exe_args, (
        "EXE must not receive the collected data files: that is a one-file bundle"
    )


def test_exe_excludes_binaries(source: str) -> None:
    exe_args = call_arguments(source, "EXE").replace(" ", "")
    assert "exclude_binaries=True" in exe_args
    assert "exclude_binaries=False" not in exe_args


def test_collect_receives_the_binaries_and_datas(source: str) -> None:
    """The mirror image of the previous test: the shared libraries go in the tree."""
    collect_args = call_arguments(source, "COLLECT")
    assert "a.binaries" in collect_args
    assert "a.datas" in collect_args


def test_spec_never_asks_for_a_onefile_build(source: str) -> None:
    """No stray ``--onefile``/``onefile=True`` outside the explanatory header.

    The header deliberately discusses ``--onefile`` at length, so only lines that
    are not comments are examined.
    """
    code_lines = [
        line for line in source.splitlines()
        if line.split("#", 1)[0].strip()
    ]
    code = "\n".join(line.split("#", 1)[0] for line in code_lines)
    assert "onefile" not in code.lower()


def test_spec_documents_why_onefile_is_forbidden(source: str) -> None:
    """The reasoning must live in the file, or someone will "optimise" it away."""
    lowered = source.lower()
    assert "--onefile" in lowered
    assert "lgpl" in lowered
    assert "4(d)(1)" in lowered or "section 4(d)(1)" in lowered


def test_qt_binaries_are_not_stripped_or_packed(source: str) -> None:
    """Stripping or UPX-packing Qt produces a modified LGPL library.

    Modifications to an LGPL library must be published under the LGPL, so the
    only safe setting is to leave the shipped Qt byte-for-byte as supplied.
    """
    for call in ("EXE", "COLLECT"):
        args = call_arguments(source, call).replace(" ", "")
        assert "strip=False" in args, f"{call} must not strip the Qt binaries"
        assert "upx=False" in args, f"{call} must not UPX-pack the Qt binaries"
        assert "strip=True" not in args
        assert "upx=True" not in args


# ----------------------------------------------------------- GPL-only modules


@pytest.mark.parametrize("module", GPL_ONLY)
def test_gpl_only_qt_module_is_excluded(source: str, module: str) -> None:
    excludes = literal(source, "EXCLUDES")
    assert module in excludes, (
        f"{module} is GPL-3.0-only; leaving it out of excludes risks a hidden "
        "import relicensing the entire product under GPL-3.0"
    )


def test_gpl_only_list_matches_the_excludes(source: str) -> None:
    """``build.py`` reads GPL_ONLY_QT_MODULES; it must agree with EXCLUDES."""
    declared = literal(source, "GPL_ONLY_QT_MODULES")
    excludes = set(literal(source, "EXCLUDES"))
    assert set(declared) == set(GPL_ONLY)
    assert set(declared) <= excludes


def test_tooling_modules_are_excluded(source: str) -> None:
    """A commercial bundle has no business shipping a test runner."""
    excludes = set(literal(source, "EXCLUDES"))
    assert {"pytest", "tkinter"} <= excludes


def test_analysis_passes_the_excludes(source: str) -> None:
    """Declaring EXCLUDES and forgetting to wire it up would be silent."""
    analysis_args = call_arguments(source, "Analysis").replace(" ", "")
    assert "excludes=EXCLUDES" in analysis_args


def test_collected_binaries_are_filtered_for_gpl_only_components(source: str) -> None:
    """``excludes`` covers Python imports; Qt DLLs can arrive by other routes."""
    assert "_without_gpl_only(a.binaries)" in source.replace(" ", "")
    assert "_without_gpl_only(a.datas)" in source.replace(" ", "")


# --------------------------------------------------------------- licence data


@pytest.mark.parametrize("relative", REQUIRED_IN_DATAS)
def test_required_licence_file_is_listed_in_datas(source: str, relative: str) -> None:
    required = literal(source, "REQUIRED_LICENCE_FILES")
    sources = [entry[0] for entry in required]
    assert relative in sources, (
        f"{relative} must be bundled; the licences dialog reads it at runtime and "
        "LGPL-3.0 4(b) requires it to accompany the distribution"
    )


def test_required_licence_files_keep_their_destination_paths(source: str) -> None:
    """``LicensesDialog`` resolves ``LICENSES/<name>`` relative to ``sys._MEIPASS``."""
    required = dict(literal(source, "REQUIRED_LICENCE_FILES"))
    for relative, destination in required.items():
        expected = "LICENSES" if relative.startswith("LICENSES/") else "."
        assert destination == expected, (
            f"{relative} must land in {expected!r}, not {destination!r}"
        )


@pytest.mark.parametrize("relative", REQUIRED_IN_DATAS)
def test_required_licence_file_exists_in_the_checkout(relative: str) -> None:
    """The spec would raise SystemExit on a missing file; catch it here instead."""
    assert (ROOT / relative).is_file()


def test_datas_are_wired_into_the_analysis(source: str) -> None:
    analysis_args = call_arguments(source, "Analysis").replace(" ", "")
    assert "datas=DATAS" in analysis_args


# ------------------------------------------------- what PyInstaller cannot see
#
# Twice now a feature has shipped missing because nothing imported it where
# PyInstaller could see the import. Both times the bundle passed every check and
# failed only when a user chose the feature, because both failure paths are
# silent by design: a missing exporter reports "format unavailable" and a
# missing inspector leaves its button disabled.


def test_spec_declares_the_entry_point_targets():
    """Entry points are resolved by name at run time, so no import names them."""
    source = SPEC.read_text(encoding="utf-8")
    for module in ("makeyourtree_studio.export.raster",
                   "makeyourtree_studio.guide.inspect"):
        assert module in source, (
            f"{module} backs an entry point, so PyInstaller never sees it "
            f"imported; without it in hiddenimports the feature vanishes from "
            f"the bundle with no error")


def test_spec_declares_the_deferred_dialog_import():
    """main_window imports the guide dialog inside the handler, not at import
    time, so that start-up does not pay for a dialog most sessions never open.
    That deferral hides it from PyInstaller."""
    assert "makeyourtree_studio.dialogs.guide_dialog" in SPEC.read_text(encoding="utf-8")


def test_spec_collects_package_metadata():
    """entry_points() reads dist-info, which PyInstaller does not collect on its
    own. Without this the registry is empty and every optional feature is gone."""
    source = SPEC.read_text(encoding="utf-8")
    assert "copy_metadata" in source
    assert "makeyourtree" in source.split("copy_metadata", 1)[1][:80]


def test_every_registered_entry_point_is_a_hidden_import():
    """The two lists must not drift apart.

    Reads the entry points out of pyproject rather than repeating them, so
    adding a third one and forgetting the spec fails here rather than in a
    user's hands.
    """
    import re

    # Only the custom groups. The console_scripts and gui_scripts entries name
    # modules PyInstaller reaches through the launcher's own imports, so they
    # need no help; the custom groups are the ones resolved purely by name.
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    registered = set()
    for group in ("makeyourtree.exporters", "makeyourtree.figure_inspectors"):
        block = pyproject.split(f'[project.entry-points."{group}"]', 1)
        if len(block) < 2:
            continue
        body = block[1].split("\n[", 1)[0]
        registered.update(re.findall(r'=\s*"([\w.]+):', body))
    assert registered, "expected custom entry points in pyproject.toml"

    source = SPEC.read_text(encoding="utf-8")
    missing = sorted(m for m in registered if m not in source)
    assert not missing, (
        f"these modules back entry points but are not named in the spec, so "
        f"they will be absent from the bundle: {missing}")

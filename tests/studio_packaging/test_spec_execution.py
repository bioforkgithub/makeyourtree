# SPDX-License-Identifier: MIT
"""Execute the spec with PyInstaller's globals stubbed out.

The other spec tests read the file statically, which cannot tell whether
``_licence_datas()`` actually resolves to files that exist or whether the
GPL-only filter really removes anything. Running the spec with fake
``Analysis``/``PYZ``/``EXE``/``COLLECT`` gives us that, in milliseconds, without
a build toolchain — and it catches a spec that would blow up minutes into a
release build.

The entry-script guard runs for real. It used to be neutralised, which is part of
why the spec spent months pointing at ``app.py`` -- a module PyInstaller would
execute as ``__main__``, so its relative imports failed at start-up and the
windowed bundle died with status 1 and no message. The launcher now lives beside
the spec, so the guard costs nothing and one of the tests below pins the choice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "src" / "makeyourtree_studio" / "packaging" / "makeyourtree.spec"


class _Recorder:
    """Stands in for a PyInstaller build step, recording how it was called."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.binaries = list(kwargs.get("binaries", []))
        self.datas = list(kwargs.get("datas", []))
        self.scripts = ["<scripts>"]
        self.pure = []
        self.zipped_data = []


@pytest.fixture(scope="module")
def executed() -> dict[str, Any]:
    """Namespace left behind by running the spec against stubbed globals."""
    source = SPEC.read_text(encoding="utf-8")
    namespace: dict[str, Any] = {
        "__file__": str(SPEC),
        "SPECPATH": str(SPEC.parent),
        "Analysis": type("Analysis", (_Recorder,), {}),
        "PYZ": type("PYZ", (_Recorder,), {}),
        "EXE": type("EXE", (_Recorder,), {}),
        "COLLECT": type("COLLECT", (_Recorder,), {}),
        "BUNDLE": type("BUNDLE", (_Recorder,), {}),
    }
    exec(compile(source, str(SPEC), "exec"), namespace)
    return namespace


def test_spec_resolves_the_project_root(executed: dict[str, Any]) -> None:
    assert executed["PROJECT_ROOT"] == ROOT


def test_every_bundled_data_path_exists(executed: dict[str, Any]) -> None:
    """``_licence_datas`` raises SystemExit on a missing file; prove it does not
    have to, i.e. that the checkout really carries everything we must ship.

    ``exists`` rather than ``is_file`` because ``copy_metadata`` contributes the
    ``.dist-info`` **directory**, which is what makes the entry points -- and so
    the optional exporters and the figure inspector -- resolve inside a frozen
    build. The licence entries are separately pinned as files below.
    """
    for source, _destination in executed["DATAS"]:
        assert Path(source).exists(), f"{source} is listed in datas but absent"


def test_the_required_licence_entries_are_files(executed: dict[str, Any]) -> None:
    required = {"GPL-3.0.txt", "LGPL-3.0.txt", "MIT.txt",
                "THIRD-PARTY-NOTICES.md", "LICENSE.md"}
    for source, _destination in executed["DATAS"]:
        path = Path(source)
        if path.name in required:
            assert path.is_file(), f"{source} must be a file"


def test_licence_datas_cover_the_required_set(executed: dict[str, Any]) -> None:
    names = {Path(source).name for source, _ in executed["DATAS"]}
    assert {
        "GPL-3.0.txt",
        "LGPL-3.0.txt",
        "MIT.txt",
        "THIRD-PARTY-NOTICES.md",
        "LICENSE.md",
    } <= names


def test_licence_datas_keep_their_destinations(executed: dict[str, Any]) -> None:
    """``LicensesDialog`` resolves ``LICENSES/<name>`` under ``sys._MEIPASS``."""
    destinations = {Path(source).name: dest for source, dest in executed["DATAS"]}
    assert destinations["GPL-3.0.txt"] == "LICENSES"
    assert destinations["LGPL-3.0.txt"] == "LICENSES"
    assert destinations["THIRD-PARTY-NOTICES.md"] == "."
    assert destinations["LICENSE.md"] == "."


def test_licence_datas_have_no_duplicates(executed: dict[str, Any]) -> None:
    """The LICENSES/ sweep must not re-add the files listed explicitly."""
    pairs = [(Path(s).resolve(), d) for s, d in executed["DATAS"]]
    assert len(pairs) == len(set(pairs))


def test_gpl_only_filter_removes_forbidden_binaries(executed: dict[str, Any]) -> None:
    """``excludes`` only covers Python imports; a Qt DLL can arrive another way."""
    filtered = executed["_without_gpl_only"](
        [
            ("Qt6Charts.dll", "/build/Qt6Charts.dll", "BINARY"),
            ("Qt6DataVisualization.dll", "/build/Qt6DataVisualization.dll", "BINARY"),
            ("PySide6/QtVirtualKeyboard.pyd", "/build/QtVirtualKeyboard.pyd", "BINARY"),
            ("Qt6Core.dll", "/build/Qt6Core.dll", "BINARY"),
            ("Qt6Widgets.dll", "/build/Qt6Widgets.dll", "BINARY"),
        ]
    )
    assert [entry[0] for entry in filtered] == ["Qt6Core.dll", "Qt6Widgets.dll"]


def test_gpl_only_filter_keeps_permitted_qt_libraries(executed: dict[str, Any]) -> None:
    """An over-broad filter that stripped real Qt libraries would break the app."""
    entries = [
        ("Qt6Core.dll", "/build/Qt6Core.dll", "BINARY"),
        ("Qt6Gui.dll", "/build/Qt6Gui.dll", "BINARY"),
        ("Qt6Svg.dll", "/build/Qt6Svg.dll", "BINARY"),
        ("libQt6PrintSupport.so.6", "/build/libQt6PrintSupport.so.6", "BINARY"),
    ]
    assert executed["_without_gpl_only"](entries) == entries


def test_the_filter_does_not_eat_the_licence_files(executed: dict[str, Any]) -> None:
    """The GPL-only sweep runs over the data files too; it must leave the legal
    documents alone, or the bundle silently loses its notices."""
    survived = {Path(source).name for source, _ in executed["a"].datas}
    assert {Path(source).name for source, _ in executed["DATAS"]} == survived


def test_exe_is_a_thin_launcher(executed: dict[str, Any]) -> None:
    exe = executed["exe"]
    assert exe.kwargs["exclude_binaries"] is True
    assert exe.kwargs["strip"] is False
    assert exe.kwargs["upx"] is False


def test_exe_never_receives_the_collected_binaries(executed: dict[str, Any]) -> None:
    """The one-file pattern passes the binaries positionally to EXE."""
    analysis = executed["a"]
    for argument in executed["exe"].args:
        assert argument is not analysis.binaries
        assert argument is not analysis.datas


def test_collect_receives_them_instead(executed: dict[str, Any]) -> None:
    analysis = executed["a"]
    collect = executed["coll"]
    assert any(argument is analysis.binaries for argument in collect.args)
    assert any(argument is analysis.datas for argument in collect.args)
    assert collect.kwargs["strip"] is False
    assert collect.kwargs["upx"] is False


def test_analysis_excludes_the_gpl_only_modules(executed: dict[str, Any]) -> None:
    excludes = set(executed["a"].kwargs["excludes"])
    assert set(executed["GPL_ONLY_QT_MODULES"]) <= excludes


def test_entry_script_is_the_launcher_not_the_app_module(executed: dict[str, Any]) -> None:
    """PyInstaller runs the entry script as ``__main__``, with no package context.

    Pointing it at ``makeyourtree_studio/app.py`` therefore breaks every relative
    import in the application the moment the bundle starts, and a windowed build
    reports that as a bare exit status 1. The launcher reaches ``app`` through an
    absolute import instead, so this is a start-up correctness guard, not a
    preference about file layout.
    """
    entry = Path(executed["ENTRY_SCRIPT"])
    assert entry.name == "launcher.py", (
        f"entry script is {entry.name}; a module inside the makeyourtree_studio package "
        "cannot be a PyInstaller entry script -- its relative imports would fail"
    )
    assert entry.is_file(), f"{entry} must exist for the build to start"
    text = entry.read_text(encoding="utf-8")
    assert "from makeyourtree_studio.app import main" in text, (
        "the launcher must reach the application by absolute import"
    )

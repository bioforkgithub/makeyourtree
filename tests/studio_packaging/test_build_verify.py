# SPDX-License-Identifier: MIT
"""The build driver's verification logic, exercised against fabricated bundles.

PyInstaller is never run here: a release build takes minutes and needs a compiler
toolchain, and neither is a reasonable thing to put in a unit test. What is worth
testing is that each licence failure mode is actually *detected*, which needs a
broken bundle on demand — something a real build will not politely provide.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Callable, Sequence

import pytest

from makeyourtree_studio.packaging import build as build_module
from makeyourtree_studio.packaging.build import (
    APP_NAME,
    SPEC_PATH,
    BuildError,
    Check,
    assert_verified,
    bundle_root,
    format_report,
    gpl_only_modules,
    spec_literal,
    verify_bundle,
    verify_spec,
)

Factory = Callable[[Sequence[str]], Path]


def failed(checks: list[Check]) -> list[str]:
    return [c.name for c in checks if not c.ok]


# ------------------------------------------------------------- spec reading


def test_spec_path_points_at_the_real_spec() -> None:
    assert SPEC_PATH.is_file()
    assert SPEC_PATH.name == "makeyourtree.spec"


def test_gpl_only_modules_are_read_from_the_spec() -> None:
    """The verifier must derive the forbidden list from the spec, not repeat it."""
    assert set(gpl_only_modules()) == {
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtVirtualKeyboard",
    }


def test_spec_literal_rejects_a_missing_name() -> None:
    with pytest.raises(BuildError, match="does not define"):
        spec_literal("NO_SUCH_CONSTANT")


def test_spec_literal_rejects_a_non_literal(tmp_path: Path) -> None:
    """Non-literals would force us to execute the spec to read it, which is both
    impossible outside PyInstaller and a code-execution hazard."""
    spec = tmp_path / "x.spec"
    spec.write_text("EXCLUDES = list(SOMETHING)\n", encoding="utf-8")
    with pytest.raises(BuildError, match="plain literal"):
        spec_literal("EXCLUDES", spec_path=spec)


def test_the_shipped_spec_passes_its_own_verification() -> None:
    checks = verify_spec()
    assert failed(checks) == [], format_report(checks)
    assert len(checks) >= 5


def test_verify_spec_catches_a_renamed_bundle(tmp_path: Path) -> None:
    """The verifier looks for ``dist/<APP_NAME>``; a rename there would make every
    later check inspect an empty directory and pass for the wrong reason."""
    doctored = tmp_path / "renamed.spec"
    text = SPEC_PATH.read_text(encoding="utf-8").replace(
        'APP_NAME = "MakeYourTreeStudio"', 'APP_NAME = "SomethingElse"'
    )
    assert text != SPEC_PATH.read_text(encoding="utf-8"), "the doctoring did not apply"
    doctored.write_text(text, encoding="utf-8")
    assert "bundle name agrees with the spec" in failed(verify_spec(spec_path=doctored))


def test_verify_spec_rejects_a_spec_that_drops_a_gpl_exclusion(tmp_path: Path) -> None:
    doctored = tmp_path / "doctored.spec"
    text = SPEC_PATH.read_text(encoding="utf-8").replace(
        '    "PySide6.QtCharts",\n    "PySide6.QtDataVisualization",\n'
        '    "PySide6.QtVirtualKeyboard",\n'
        "    # Test and tooling modules",
        "    # Test and tooling modules",
    )
    assert text != SPEC_PATH.read_text(encoding="utf-8"), "the doctoring did not apply"
    doctored.write_text(text, encoding="utf-8")
    checks = verify_spec(spec_path=doctored)
    assert "spec excludes every GPL-3.0-only Qt add-on" in failed(checks)


def test_verify_spec_rejects_a_onefile_spec(tmp_path: Path) -> None:
    """Simulate the "optimisation" the header warns about and prove it is caught."""
    doctored = tmp_path / "onefile.spec"
    text = SPEC_PATH.read_text(encoding="utf-8")
    text = text.replace("    exclude_binaries=True,\n", "    a.binaries,\n")
    text = text.replace("coll = COLLECT(", "_collected = _identity(")
    assert text != SPEC_PATH.read_text(encoding="utf-8"), "the doctoring did not apply"
    doctored.write_text(text, encoding="utf-8")
    checks = verify_spec(spec_path=doctored)
    names = failed(checks)
    assert "spec builds a onedir tree (COLLECT present)" in names
    assert "executable is a thin launcher, Qt stays replaceable" in names
    assert "EXE sets exclude_binaries=True" in names


# ---------------------------------------------------------- bundle inspection


def test_a_well_formed_bundle_passes_every_check(good_bundle: Path) -> None:
    checks = verify_bundle(good_bundle)
    assert failed(checks) == [], format_report(checks)


def test_missing_bundle_directory_fails(tmp_path: Path) -> None:
    """A one-file build leaves a bare executable and no directory at all."""
    checks = verify_bundle(tmp_path / "MakeYourTreeStudio")
    assert failed(checks) == ["bundle directory exists"]


def test_missing_launcher_fails(make_bundle: Factory, bundle_files) -> None:
    bundle = make_bundle([f for f in bundle_files if not f.endswith(".exe")])
    assert "launcher executable present" in failed(verify_bundle(bundle))


@pytest.mark.parametrize(
    "dropped",
    [
        "_internal/LICENSES/GPL-3.0.txt",
        "_internal/LICENSES/LGPL-3.0.txt",
        "_internal/LICENSES/MIT.txt",
        "_internal/THIRD-PARTY-NOTICES.md",
    ],
)
def test_each_missing_licence_file_fails_the_build(
    make_bundle: Factory, bundle_files, dropped: str
) -> None:
    """Shipping without any one of these breaches LGPL-3.0 4(a), 4(b) or 4(c)."""
    assert dropped in bundle_files
    bundle = make_bundle([f for f in bundle_files if f != dropped])
    expected = f"licence file bundled: {dropped.removeprefix('_internal/')}"
    assert expected in failed(verify_bundle(bundle))


def test_licence_files_are_found_in_a_flat_layout(
    make_bundle: Factory, bundle_files
) -> None:
    """PyInstaller 5 puts data files beside the launcher, PyInstaller 6 in
    ``_internal/``. Both layouts satisfy the obligation, so both must pass."""
    bundle = make_bundle([f.replace("_internal/", "") for f in bundle_files])
    assert failed(verify_bundle(bundle)) == []


def test_bundle_without_separate_qt_libraries_fails(
    make_bundle: Factory, bundle_files
) -> None:
    """The signature of an embedded Qt: no shared libraries to replace."""
    bundle = make_bundle([f for f in bundle_files if "Qt6" not in f])
    assert "Qt ships as separate shared libraries" in failed(verify_bundle(bundle))


def test_bundle_with_only_one_qt_library_fails(
    make_bundle: Factory, bundle_files
) -> None:
    """Two libraries is the floor: a single one means Qt was partly embedded."""
    bundle = make_bundle(
        [f for f in bundle_files if "Qt6" not in f] + ["_internal/Qt6Core.dll"]
    )
    assert "Qt ships as separate shared libraries" in failed(verify_bundle(bundle))


def test_linux_style_shared_libraries_are_recognised(
    make_bundle: Factory, bundle_files
) -> None:
    """The verifier must work on every platform we ship, not just the build host."""
    files = [f for f in bundle_files if "Qt6" not in f and not f.endswith(".exe")]
    files += [
        "MakeYourTreeStudio",
        "_internal/libQt6Core.so.6",
        "_internal/libQt6Gui.so.6",
        "_internal/libQt6Widgets.so.6",
    ]
    bundle = make_bundle(files)
    assert failed(verify_bundle(bundle)) == []


@pytest.mark.parametrize(
    "intruder",
    [
        "_internal/Qt6Charts.dll",
        "_internal/libQt6DataVisualization.so.6",
        "_internal/PySide6/QtVirtualKeyboard.pyd",
        "_internal/Qt6VirtualKeyboard.dll",
    ],
)
def test_a_gpl_only_qt_component_fails_the_build(
    make_bundle: Factory, bundle_files, intruder: str
) -> None:
    """One GPL-3.0-only Qt library in the tree makes the whole product GPL."""
    bundle = make_bundle(list(bundle_files) + [intruder])
    checks = verify_bundle(bundle)
    assert "no GPL-3.0-only Qt add-on in the bundle" in failed(checks)
    detail = next(c.detail for c in checks if not c.ok)
    assert Path(intruder).name in detail


def test_permitted_qt_modules_are_not_mistaken_for_forbidden_ones(
    good_bundle: Path,
) -> None:
    """Guard against an over-broad name match banning legitimate Qt libraries."""
    checks = verify_bundle(good_bundle)
    assert next(c for c in checks if c.name.startswith("no GPL-3.0-only")).ok


# ----------------------------------------------------------------- reporting


def test_assert_verified_names_every_failure() -> None:
    checks = [
        Check("first", False, "broke"),
        Check("second", True, "fine"),
        Check("third", False, "also broke"),
    ]
    with pytest.raises(BuildError) as excinfo:
        assert_verified(checks)
    message = str(excinfo.value)
    assert "2 of 3" in message
    assert "first" in message and "third" in message
    assert "second" not in message


def test_assert_verified_accepts_a_clean_run() -> None:
    assert_verified([Check("ok", True, "")])


def test_format_report_counts_passes() -> None:
    report = format_report([Check("a", True, "x"), Check("b", False, "y")])
    assert "PASS  a" in report
    assert "FAIL  b" in report
    assert "1/2 checks passed" in report


def test_bundle_root_is_named_after_the_app() -> None:
    assert bundle_root(Path("dist")) == Path("dist") / APP_NAME


# ------------------------------------------------------------ the build path


def test_pyinstaller_version_reports_a_missing_tool(monkeypatch) -> None:
    """A missing build tool must be named, not surface as an obscure ImportError."""
    monkeypatch.setitem(sys.modules, "PyInstaller", None)
    with pytest.raises(BuildError, match="PyInstaller is not installed"):
        build_module.pyinstaller_version()


def test_pyinstaller_version_reads_the_installed_version(monkeypatch) -> None:
    fake = types.ModuleType("PyInstaller")
    fake.__version__ = "6.99.0"
    monkeypatch.setitem(sys.modules, "PyInstaller", fake)
    assert build_module.pyinstaller_version() == "6.99.0"


def test_run_pyinstaller_never_requests_a_onefile_build(monkeypatch, tmp_path: Path) -> None:
    """The driver is the only supported release path, so its command line is
    part of the licence guarantee."""
    captured: dict[str, list[str]] = {}

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        return Result()

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)
    build_module.run_pyinstaller(
        dist_dir=tmp_path / "dist", work_dir=tmp_path / "work", clean=True
    )
    command = captured["command"]
    assert "--onefile" not in command
    assert "-F" not in command
    assert str(SPEC_PATH) in command
    assert "--clean" in command


def test_run_pyinstaller_raises_on_a_failed_process(monkeypatch, tmp_path: Path) -> None:
    class Result:
        returncode = 2

    monkeypatch.setattr(build_module.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(BuildError, match="status 2"):
        build_module.run_pyinstaller(dist_dir=tmp_path, work_dir=tmp_path)


def test_build_with_skip_build_only_verifies(monkeypatch, good_bundle: Path) -> None:
    """``--verify-only`` must audit an artefact without touching PyInstaller."""
    def explode(*args, **kwargs):
        raise AssertionError("PyInstaller must not run in verify-only mode")

    monkeypatch.setattr(build_module, "run_pyinstaller", explode)
    checks = build_module.build(
        dist_dir=good_bundle.parent,
        work_dir=good_bundle.parent / "work",
        skip_build=True,
    )
    assert failed(checks) == [], format_report(checks)


def test_main_reports_failure_for_a_missing_bundle(tmp_path: Path) -> None:
    code = build_module.main(
        ["--verify-only", "--dist", str(tmp_path / "empty"), "--work", str(tmp_path)]
    )
    assert code == 1


def test_main_succeeds_for_a_good_bundle(good_bundle: Path) -> None:
    code = build_module.main(
        [
            "--verify-only",
            "--dist", str(good_bundle.parent),
            "--work", str(good_bundle.parent / "work"),
        ]
    )
    assert code == 0

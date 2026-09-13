# SPDX-License-Identifier: MIT
"""Build driver for the MakeYourTree Studio distribution, and its safety net.

Running PyInstaller is the easy half. The half that matters is what happens
afterwards, because the ways a bundle goes wrong are silent: PyInstaller reports
success, the application starts, and the only visible symptom is a licence breach
that nobody notices until a customer asks for the Qt source.

Three failures we cannot detect by launching the app:

* **A licence text went missing.** ``LicensesDialog`` shows an empty page and the
  distribution no longer satisfies LGPL-3.0 4(a)/4(b)/4(c).
* **The bundle turned into a one-file build.** Qt is then packed inside the
  executable and a user cannot replace it, so LGPL-3.0 4(d)(1) is not met and we
  have no right to distribute Qt at all.
* **A GPL-3.0-only Qt add-on was pulled in transitively.** That relicenses the
  whole product under GPL-3.0 and voids the commercial EULA.

So :func:`verify_bundle` inspects the produced directory and every check has to
pass before the build is called a success. The list of forbidden Qt add-ons is
read out of ``makeyourtree.spec`` rather than repeated here, so the spec stays the
single source of truth and the two can never disagree.
"""

from __future__ import annotations

import argparse
import ast
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

__all__ = [
    "BuildError",
    "Check",
    "SPEC_PATH",
    "APP_NAME",
    "assert_verified",
    "bundle_root",
    "format_report",
    "gpl_only_modules",
    "spec_literal",
    "verify_bundle",
]

_LOG = logging.getLogger("makeyourtree.build")

SPEC_PATH = Path(__file__).resolve().parent / "makeyourtree.spec"
PROJECT_ROOT = SPEC_PATH.parents[3]

#: Must match ``APP_NAME`` in the spec; :func:`verify_spec` cross-checks it.
APP_NAME = "MakeYourTreeStudio"

#: Paths, relative to the bundle root, that every distribution must contain.
#: These are the files ``LicensesDialog`` opens at runtime.
REQUIRED_LICENCE_FILES: tuple[str, ...] = (
    "LICENSES/GPL-3.0.txt",
    "LICENSES/LGPL-3.0.txt",
    "LICENSES/MIT.txt",
    "THIRD-PARTY-NOTICES.md",
)

#: PyInstaller 6 moves data files into ``_internal/`` beside the launcher. Both
#: layouts are accepted so the verifier works with older and newer PyInstaller.
_DATA_PREFIXES: tuple[str, ...] = ("", "_internal")

#: A Qt shared library on any of the three platforms: ``Qt6Core.dll``,
#: ``libQt6Core.so.6``, ``libQt6Core.6.dylib``, or a framework binary ``QtCore``
#: inside ``QtCore.framework``.
_QT_LIBRARY = re.compile(
    r"^(?:lib)?Qt6?[A-Za-z0-9_]*(?:\.[0-9]+)*\.(?:dll|dylib|so)(?:\.[0-9]+)*$",
    re.IGNORECASE,
)


class BuildError(RuntimeError):
    """A build or verification step failed. Always fatal — never warn and go on."""


@dataclass(frozen=True, slots=True)
class Check:
    """One verification result, kept as data so tests can assert on it."""

    name: str
    ok: bool
    detail: str


# --------------------------------------------------------- reading the spec


def spec_literal(name: str, *, spec_path: Path = SPEC_PATH) -> object:
    """Return the literal assigned to *name* at the top level of the spec.

    Parsed with :mod:`ast` rather than imported, because executing a PyInstaller
    spec outside PyInstaller fails on the injected ``Analysis``/``EXE`` builtins.
    Static parsing also means a spec that has been sabotaged cannot run code here.
    """
    try:
        source = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildError(f"cannot read {spec_path}: {exc}") from exc
    try:
        module = ast.parse(source, filename=str(spec_path))
    except SyntaxError as exc:
        raise BuildError(f"{spec_path} is not valid Python: {exc}") from exc
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if name not in targets:
            continue
        try:
            return ast.literal_eval(node.value)
        except (ValueError, SyntaxError) as exc:
            raise BuildError(
                f"{name} in {spec_path.name} must be a plain literal so it can be "
                f"read without executing the spec: {exc}"
            ) from exc
    raise BuildError(f"{spec_path.name} does not define {name}")


def gpl_only_modules(*, spec_path: Path = SPEC_PATH) -> tuple[str, ...]:
    """The forbidden Qt add-ons, as declared by the spec.

    Deliberately not hard-coded in this file: one list, in the spec, keeps the
    exclusion and the verification from drifting apart.
    """
    value = spec_literal("GPL_ONLY_QT_MODULES", spec_path=spec_path)
    if not isinstance(value, (tuple, list)) or not value:
        raise BuildError("GPL_ONLY_QT_MODULES must be a non-empty tuple of module names")
    return tuple(str(v) for v in value)


def _forbidden_name_fragments(modules: Iterable[str]) -> list[str]:
    """Lower-case file-name fragments that betray a forbidden Qt add-on.

    A module ``PySide6.QtFoo`` can reach the bundle as the extension module
    ``QtFoo.pyd`` or as the Qt shared library ``Qt6Foo.dll`` / ``libQt6Foo.so.6``
    / ``QtFoo.framework``, and only the first spelling contains the module name,
    so the ``Qt6``-infixed form is generated too.
    """
    fragments: list[str] = []
    for dotted in modules:
        leaf = dotted.rsplit(".", 1)[-1]
        fragments.append(leaf.lower())
        if leaf.lower().startswith("qt"):
            fragments.append(("qt6" + leaf[2:]).lower())
    return fragments


def verify_spec(*, spec_path: Path = SPEC_PATH) -> list[Check]:
    """Check the spec itself before spending minutes building from it.

    Catches the two edits that would silently produce an unshippable bundle: a
    forbidden module dropped from ``excludes``, and the onedir structure being
    collapsed into a one-file executable.
    """
    checks: list[Check] = []
    excludes = spec_literal("EXCLUDES", spec_path=spec_path)
    if not isinstance(excludes, (list, tuple)):
        raise BuildError("EXCLUDES must be a list of module names")
    excluded = {str(e) for e in excludes}
    forbidden = gpl_only_modules(spec_path=spec_path)
    missing = [m for m in forbidden if m not in excluded]
    checks.append(Check(
        "spec excludes every GPL-3.0-only Qt add-on",
        not missing,
        "all listed in EXCLUDES" if not missing else f"missing from EXCLUDES: {missing}",
    ))

    source = spec_path.read_text(encoding="utf-8")
    has_collect = re.search(r"^\s*coll\s*=\s*COLLECT\(", source, re.MULTILINE) is not None
    checks.append(Check(
        "spec builds a onedir tree (COLLECT present)",
        has_collect,
        "COLLECT(...) found" if has_collect else "no COLLECT step: this is a one-file build",
    ))

    exe_args = _call_arguments(source, "EXE")
    onefile = exe_args is None or "a.binaries" in exe_args
    checks.append(Check(
        "executable is a thin launcher, Qt stays replaceable",
        not onefile,
        "EXE does not receive the collected binaries"
        if not onefile else
        "EXE bundles the binaries: LGPL-3.0 4(d)(1) is not satisfied",
    ))
    thin = exe_args is not None and "exclude_binaries=True" in exe_args.replace(" ", "")
    checks.append(Check(
        "EXE sets exclude_binaries=True",
        thin,
        "onedir launcher" if thin else "exclude_binaries is not True",
    ))

    # A renamed bundle would make every path-based check below look at an empty
    # directory and pass vacuously, so the two names must agree.
    spec_app = spec_literal("APP_NAME", spec_path=spec_path)
    checks.append(Check(
        "bundle name agrees with the spec",
        spec_app == APP_NAME,
        f"{APP_NAME!r}" if spec_app == APP_NAME
        else f"spec says {spec_app!r}, build.py expects {APP_NAME!r}",
    ))
    return checks


def _call_arguments(source: str, func: str) -> str | None:
    """The argument text of the first top-level ``func(...)`` call, comments stripped.

    Hand-rolled bracket matching rather than :mod:`ast` because the spec's calls
    reference names PyInstaller injects; we only want the raw text.
    """
    match = re.search(rf"^\s*\w+\s*=\s*{func}\(", source, re.MULTILINE)
    if match is None:
        return None
    start = match.end()
    depth = 1
    for index in range(start, len(source)):
        char = source[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                body = source[start:index]
                return "\n".join(
                    line.split("#", 1)[0] for line in body.splitlines()
                )
    return None


# ------------------------------------------------------- inspecting a bundle


def bundle_root(dist_dir: Path, *, app_name: str = APP_NAME) -> Path:
    """Where COLLECT wrote the distribution."""
    return dist_dir / app_name


def _executable_names(app_name: str) -> tuple[str, ...]:
    return (app_name, f"{app_name}.exe")


def _find_executable(bundle: Path, app_name: str) -> Path | None:
    names = _executable_names(app_name)
    for candidate in (bundle, bundle / "Contents" / "MacOS"):
        for name in names:
            path = candidate / name
            if path.is_file():
                return path
    return None


def _all_files(bundle: Path) -> list[Path]:
    return [p for p in bundle.rglob("*") if p.is_file()]


def _find_data_file(bundle: Path, relative: str) -> Path | None:
    for prefix in _DATA_PREFIXES:
        candidate = bundle / prefix / relative if prefix else bundle / relative
        if candidate.is_file():
            return candidate
    # macOS .app bundles nest the payload; search there rather than declaring a
    # licence file missing because of a layout difference.
    for nested in ("Contents/Resources", "Contents/Frameworks", "Contents/MacOS"):
        candidate = bundle / nested / relative
        if candidate.is_file():
            return candidate
    return None


def verify_bundle(
    bundle: Path,
    *,
    app_name: str = APP_NAME,
    forbidden_modules: Sequence[str] | None = None,
    spec_path: Path = SPEC_PATH,
) -> list[Check]:
    """Inspect a produced bundle directory and report every check.

    Pure inspection: it never modifies the bundle, so it can be run against a
    downloaded artefact as an audit step, not only right after a build.
    """
    if forbidden_modules is None:
        forbidden_modules = gpl_only_modules(spec_path=spec_path)

    checks: list[Check] = []

    if not bundle.is_dir():
        return [Check(
            "bundle directory exists",
            False,
            f"{bundle} is not a directory; a one-file build would produce a bare "
            "executable here instead",
        )]
    checks.append(Check("bundle directory exists", True, str(bundle)))

    executable = _find_executable(bundle, app_name)
    checks.append(Check(
        "launcher executable present",
        executable is not None,
        str(executable) if executable is not None
        else f"none of {_executable_names(app_name)} found in {bundle}",
    ))

    files = _all_files(bundle)

    for relative in REQUIRED_LICENCE_FILES:
        found = _find_data_file(bundle, relative)
        checks.append(Check(
            f"licence file bundled: {relative}",
            found is not None,
            str(found) if found is not None else "MISSING - the distribution may not ship",
        ))

    qt_libraries = sorted(
        {p.name for p in files if _QT_LIBRARY.match(p.name)}
        | {p.parent.name for p in files if p.parent.suffix == ".framework"}
    )
    core = [n for n in qt_libraries if "core" in n.lower()]
    checks.append(Check(
        "Qt ships as separate shared libraries",
        len(qt_libraries) >= 2 and bool(core),
        f"{len(qt_libraries)} Qt shared libraries alongside the launcher"
        if qt_libraries else
        "no Qt shared library found as a separate file: Qt is embedded and "
        "LGPL-3.0 4(d)(1) is not satisfied",
    ))

    fragments = _forbidden_name_fragments(forbidden_modules)
    offenders = sorted(
        {
            str(p.relative_to(bundle))
            for p in files
            if any(fragment in p.name.lower() for fragment in fragments)
        }
    )
    checks.append(Check(
        "no GPL-3.0-only Qt add-on in the bundle",
        not offenders,
        "none present" if not offenders
        else "GPL-3.0-only Qt components found, the product would become GPL: "
             + ", ".join(offenders),
    ))
    return checks


def assert_verified(checks: Sequence[Check]) -> None:
    """Raise :class:`BuildError` naming every failed check.

    All failures are reported at once: fixing one packaging problem and
    rediscovering the next on the following ten-minute build is how these get
    shipped half-fixed.
    """
    failures = [c for c in checks if not c.ok]
    if failures:
        detail = "\n".join(f"  FAIL  {c.name}: {c.detail}" for c in failures)
        raise BuildError(
            f"{len(failures)} of {len(checks)} distribution checks failed:\n{detail}"
        )


def format_report(checks: Sequence[Check]) -> str:
    """Human-readable summary of what was verified, for the build log."""
    lines = [f"{'PASS' if c.ok else 'FAIL'}  {c.name}\n        {c.detail}" for c in checks]
    passed = sum(1 for c in checks if c.ok)
    lines.append(f"{passed}/{len(checks)} checks passed")
    return "\n".join(lines)


# ---------------------------------------------------------------- the build


def pyinstaller_version() -> str:
    """Version string, or raise if PyInstaller is not importable.

    Checked before the spec runs so the failure message names the missing tool
    instead of surfacing as a confusing import error inside PyInstaller's hooks.
    """
    try:
        import PyInstaller  # noqa: PLC0415 - optional build-time dependency
    except ImportError as exc:
        raise BuildError(
            "PyInstaller is not installed in this interpreter; "
            "install it with: pip install pyinstaller"
        ) from exc
    return str(getattr(PyInstaller, "__version__", "unknown"))


def run_pyinstaller(
    *,
    spec_path: Path = SPEC_PATH,
    dist_dir: Path,
    work_dir: Path,
    clean: bool = True,
    python: str | None = None,
) -> None:
    """Execute the spec in a subprocess.

    A subprocess rather than ``PyInstaller.__main__.run`` because PyInstaller
    mutates global import state and never fully unwinds it; keeping it out of
    this process keeps the driver reusable and its exit status unambiguous.
    """
    command = [
        python or sys.executable,
        "-m",
        "PyInstaller",
        str(spec_path),
        "--distpath", str(dist_dir),
        "--workpath", str(work_dir),
        "--noconfirm",
    ]
    if clean:
        command.append("--clean")
    _LOG.info("running: %s", " ".join(command))
    result = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    if result.returncode != 0:
        raise BuildError(f"PyInstaller exited with status {result.returncode}")


def build(
    *,
    dist_dir: Path,
    work_dir: Path,
    spec_path: Path = SPEC_PATH,
    app_name: str = APP_NAME,
    clean: bool = True,
    skip_build: bool = False,
) -> list[Check]:
    """Verify the spec, build, verify the result. Returns every check performed."""
    checks = verify_spec(spec_path=spec_path)
    assert_verified(checks)
    _LOG.info("spec verified: %s", spec_path)

    if not skip_build:
        version = pyinstaller_version()
        _LOG.info("PyInstaller %s", version)
        if clean and dist_dir.exists():
            shutil.rmtree(bundle_root(dist_dir, app_name=app_name), ignore_errors=True)
        run_pyinstaller(
            spec_path=spec_path,
            dist_dir=dist_dir,
            work_dir=work_dir,
            clean=clean,
        )

    checks += verify_bundle(
        bundle_root(dist_dir, app_name=app_name),
        app_name=app_name,
        spec_path=spec_path,
    )
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point. Non-zero exit on any failed check."""
    parser = argparse.ArgumentParser(
        prog="makeyourtree-build",
        description="Build the MakeYourTree Studio distribution and verify its licence "
                    "obligations are met.",
    )
    parser.add_argument("--dist", type=Path, default=PROJECT_ROOT / "dist",
                        help="output directory for the bundle (default: ./dist)")
    parser.add_argument("--work", type=Path, default=PROJECT_ROOT / "build",
                        help="scratch directory for PyInstaller (default: ./build)")
    parser.add_argument("--spec", type=Path, default=SPEC_PATH,
                        help="spec file to build (default: the bundled one)")
    parser.add_argument("--no-clean", action="store_true",
                        help="reuse PyInstaller's cache instead of rebuilding")
    parser.add_argument("--verify-only", action="store_true",
                        help="verify an existing bundle without rebuilding it")
    args = parser.parse_args(argv)

    # A no-op when the caller already configured logging (a test runner, a CI
    # wrapper), so the driver never steals another process's log handlers.
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        checks = build(
            dist_dir=args.dist,
            work_dir=args.work,
            spec_path=args.spec,
            clean=not args.no_clean,
            skip_build=args.verify_only,
        )
    except BuildError as exc:
        _LOG.error("build failed: %s", exc)
        return 1
    _LOG.info("%s", format_report(checks))
    try:
        assert_verified(checks)
    except BuildError as exc:
        _LOG.error("%s", exc)
        return 1
    _LOG.info("distribution at %s is fit to ship", bundle_root(args.dist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

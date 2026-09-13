# SPDX-License-Identifier: MIT
"""Build the MakeYourTree user manual to PDF.

Run with ``python docs/manual/build.py``.

Two passes minimum, because the table of contents, the cross-references and the
PDF outline are all written on one pass and read on the next; a single pass
produces a manual whose contents page is empty or stale. ``latexmk`` decides how
many passes are actually needed, so it is preferred when present, with a plain
three-pass ``pdflatex`` loop as the fallback.

The figures are the vector PDFs in ``examples/gallery/``. If they are missing,
build them first::

    python tools/make_gallery.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GALLERY = ROOT / "examples" / "gallery"
TEX = HERE / "manual.tex"
PDF_NAME = "MakeYourTree-Manual.pdf"

#: Cleared after a successful build. The PDF and the sources stay.
LATEX_DEBRIS = (".aux", ".log", ".out", ".toc", ".lof", ".lot", ".fls",
                ".fdb_latexmk", ".synctex.gz", ".bbl", ".blg")


def check_figures() -> int:
    """Count the gallery PDFs the manual expects to include."""
    if not GALLERY.is_dir():
        return 0
    return len(list(GALLERY.glob("*.pdf")))


def run(command: list[str]) -> int:
    print("  $", " ".join(command))
    return subprocess.run(command, cwd=str(HERE), check=False).returncode


def build(*, keep_debris: bool = False) -> int:
    figures = check_figures()
    if figures == 0:
        print("No figures in examples/gallery/. Run first:\n"
              "    python tools/make_gallery.py", file=sys.stderr)
        return 1
    print(f"{figures} gallery figures available")

    if shutil.which("latexmk"):
        # -pdf selects pdflatex; latexmk reruns until the references settle.
        code = run(["latexmk", "-pdf", "-interaction=nonstopmode",
                    "-halt-on-error", TEX.name])
    else:
        code = 0
        for i in range(1, 4):
            print(f"  pass {i} of 3")
            code = run(["pdflatex", "-interaction=nonstopmode",
                        "-halt-on-error", TEX.name])
            if code != 0:
                break

    produced = HERE / "manual.pdf"
    if code != 0 or not produced.is_file():
        print(f"\nBuild failed. See {HERE / 'manual.log'} for the LaTeX log.",
              file=sys.stderr)
        return 1

    target = HERE / PDF_NAME
    produced.replace(target)

    if not keep_debris:
        for suffix in LATEX_DEBRIS:
            for path in HERE.glob(f"*{suffix}"):
                path.unlink(missing_ok=True)

    size = target.stat().st_size / 1e6
    print(f"\n{target.relative_to(ROOT).as_posix()}  ({size:.1f} MB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build-manual", description="Build the user manual to PDF.")
    parser.add_argument("--keep-debris", action="store_true",
                        help="keep .aux/.log/.toc, for diagnosing a bad build")
    args = parser.parse_args(argv)
    return build(keep_debris=args.keep_debris)


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-License-Identifier: MIT
"""Output formats the CLI can write, including ones this package cannot draw.

SVG is written here, in pure Python.  PNG and PDF need a rasteriser, which
means Qt, and **nothing under ``makeyourtree/`` may import a GUI toolkit** --
that rule is what lets the MIT core be installed, tested and shipped without an
LGPL runtime, and ``tests/test_licensing.py`` fails the build on a breach.

So the extra formats are discovered rather than imported.  ``makeyourtree_studio``
advertises them through a ``makeyourtree.exporters`` entry point in its package
metadata; this module reads that metadata and loads the target only when a user
actually asks for that format.  Three properties follow, and all three matter:

* the core never names the studio package in code, so the dependency arrow
  still points one way;
* installing the core alone works, and asking for PNG then fails with an
  instruction rather than an ``ImportError`` traceback; and
* a third party can add a format without patching this file.

The registry is cached because ``entry_points()`` walks the whole environment,
which is slow enough to notice in a loop over a directory of trees.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Protocol

__all__ = [
    "ExportError",
    "UnavailableFormat",
    "ENTRY_POINT_GROUP",
    "BUILTIN_FORMATS",
    "SUFFIXES",
    "available_formats",
    "format_for_path",
    "export_scene",
    "is_raster",
]

ENTRY_POINT_GROUP = "makeyourtree.exporters"

#: Formats this package can write with no optional dependency.
BUILTIN_FORMATS: tuple[str, ...] = ("svg",)

#: Extension to format, for inferring the format from the output path.
SUFFIXES: dict[str, str] = {
    ".svg": "svg",
    ".pdf": "pdf",
    ".png": "png",
}

#: Formats measured in pixels, for which ``dpi`` is meaningful.
_RASTER = frozenset({"png"})

_cache: dict[str, Callable[..., None]] | None = None


class ExportError(RuntimeError):
    """Writing the file failed."""


class UnavailableFormat(ExportError):
    """The format is known but the package that provides it is not installed."""


class Exporter(Protocol):
    """What a registered exporter must accept.

    ``dpi`` is passed to every exporter, raster or not, so the CLI does not have
    to know which is which; a vector exporter ignores it.
    """

    def __call__(self, scene: Any, path: str | os.PathLike[str], *,
                 dpi: float, background: Any = None) -> None: ...


def is_raster(fmt: str) -> bool:
    """Whether *fmt* is measured in pixels, so that ``dpi`` changes the output."""
    return fmt.lower() in _RASTER


def _export_svg(scene: Any, path: str | os.PathLike[str], *,
                dpi: float = 72.0, background: Any = None,
                title: str | None = None, **_: Any) -> None:
    """Write SVG.  Vector, so *dpi* is accepted and ignored."""
    from .svg import render_svg

    text = render_svg(scene, title=title)
    # newline="" so the bytes on disk are the renderer's bytes on every
    # platform; a figure that differs by line ending between machines defeats
    # any attempt to diff or checksum a figure.
    with open(os.fspath(path), "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _discover() -> dict[str, Callable[..., None]]:
    """Registered exporters, built-ins first, cached after the first call."""
    global _cache
    if _cache is not None:
        return _cache

    found: dict[str, Callable[..., None]] = {"svg": _export_svg}
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - importlib.metadata is stdlib on 3.12
        _cache = found
        return found

    try:
        points = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # pragma: no cover - a broken installation, not our bug
        points = ()
    for point in points:
        if point.name in found:
            continue
        try:
            found[point.name] = point.load()
        except Exception:
            # A half-installed optional dependency must not stop `render
            # figure.svg` from working. The format simply stays unavailable,
            # and asking for it says so.
            continue
    _cache = found
    return found


def available_formats() -> tuple[str, ...]:
    """Formats that can be written right now, in a stable order."""
    return tuple(sorted(_discover()))


def format_for_path(path: str | os.PathLike[str],
                    default: str = "svg") -> str:
    """Infer the format from *path*'s extension.

    Falls back to *default* rather than raising, because an explicit
    ``--format`` should win over a misleading extension and the caller decides
    which to trust.
    """
    suffix = os.path.splitext(os.fspath(path))[1].lower()
    return SUFFIXES.get(suffix, default)


def export_scene(scene: Any, path: str | os.PathLike[str], fmt: str, *,
                 dpi: float = 300.0, background: Any = None,
                 title: str | None = None) -> None:
    """Write *scene* to *path* in *fmt*.

    Raises :class:`UnavailableFormat` with an actionable message when the format
    needs an optional dependency that is not installed -- which, for a user who
    did ``pip install makeyourtree`` and then asked for a PNG, is the whole
    difference between a usable tool and a traceback.
    """
    key = fmt.lower()
    exporters = _discover()
    handler = exporters.get(key)
    if handler is None:
        if key in SUFFIXES.values():
            raise UnavailableFormat(
                f"{key.upper()} output needs the desktop extra, which supplies "
                f"the rasteriser: pip install 'makeyourtree[studio]'. "
                f"Available now: {', '.join(available_formats())}.")
        raise ExportError(
            f"unknown output format {fmt!r}; "
            f"available: {', '.join(available_formats())}")

    try:
        handler(scene, path, dpi=dpi, background=background, title=title)
    except TypeError:
        # A third-party exporter that predates one of these keywords still gets
        # to run rather than failing on an argument it never promised to take.
        handler(scene, path)

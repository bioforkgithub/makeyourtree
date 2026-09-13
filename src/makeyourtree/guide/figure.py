# SPDX-License-Identifier: MIT
"""Reading a published figure to seed the interview.

Someone with a figure they like and no idea how it was made is the hardest user
to help, because they cannot describe what they want in the vocabulary the
software uses.  They can, however, point at a PDF.

**What this does and does not do.**  It measures.  It does not recognise.  There
is no model here and no network call -- MakeYourTree does not make any -- so the
inspector reports geometric and colorimetric facts it can prove from the pixels
(is the ink arranged radially, how much of the image is saturated colour, how
many distinct colour bands there are) and turns those into *suggestions* with a
stated confidence.  Anything it cannot establish is left for the interview to
ask about, which is the honest division of labour.

The consequence to keep in mind when reading the output: an observation is
evidence, not a conclusion.  Every suggestion it produces is a pre-filled answer
the user can overrule, and the wizard shows the evidence next to it so they can.

Rendering a PDF page and decoding a PNG both need an image stack, which means
Qt, and nothing under ``makeyourtree/`` may import a GUI toolkit.  So the
inspector is discovered through the ``makeyourtree.figure_inspectors`` entry
point exactly as the raster exporters are; see
:mod:`makeyourtree.render.exporters` for why that shape was chosen.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = [
    "ENTRY_POINT_GROUP",
    "Observation",
    "FigureReading",
    "FigureError",
    "InspectorUnavailable",
    "inspect_figure",
    "inspector_available",
]

ENTRY_POINT_GROUP = "makeyourtree.figure_inspectors"

_cache: Callable[..., "FigureReading"] | None = None
_looked = False


class FigureError(RuntimeError):
    """The figure could not be read."""


class InspectorUnavailable(FigureError):
    """No inspector is installed."""


@dataclass(frozen=True, slots=True)
class Observation:
    """One measurable fact, and how much weight it deserves.

    ``evidence`` is shown to the user verbatim.  A suggestion without its
    evidence is indistinguishable from a guess, and a user who cannot tell the
    difference will either trust it too much or ignore it entirely.
    """

    key: str
    summary: str
    evidence: str = ""
    confidence: float = 0.5

    def __str__(self) -> str:
        band = ("likely" if self.confidence >= 0.75 else
                "possible" if self.confidence >= 0.45 else "uncertain")
        text = f"{self.summary} ({band})"
        return f"{text} -- {self.evidence}" if self.evidence else text


@dataclass(slots=True)
class FigureReading:
    """Everything an inspection produced."""

    source: str = ""
    observations: list[Observation] = field(default_factory=list)
    suggested: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        """The observations as text, for a plan's record of its own basis."""
        out = [f"Read from {os.path.basename(self.source)}:"] if self.source else []
        out += [str(observation) for observation in self.observations]
        out += list(self.notes)
        return out

    def confident(self, minimum: float = 0.75) -> list[Observation]:
        return [o for o in self.observations if o.confidence >= minimum]


def _discover() -> Callable[..., FigureReading] | None:
    global _cache, _looked
    if _looked:
        return _cache
    _looked = True
    try:
        from importlib.metadata import entry_points
        points = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # pragma: no cover - a broken installation
        points = ()
    for point in points:
        try:
            _cache = point.load()
            break
        except Exception:
            # A half-installed optional dependency must leave the interview
            # working; the figure route simply stays unavailable.
            continue
    return _cache


def inspector_available() -> bool:
    """Whether a figure can be inspected in this installation."""
    return _discover() is not None


def inspect_figure(path: str | os.PathLike[str]) -> FigureReading:
    """Measure the figure at *path* and suggest answers from what is there.

    Raises :class:`InspectorUnavailable` with an instruction when the optional
    dependency is missing, rather than a traceback: a user who installed the
    library alone should be told what to install, not shown an import error.
    """
    target = os.fspath(path)
    if not os.path.isfile(target):
        raise FigureError(f"no such file: {target}")
    handler = _discover()
    if handler is None:
        raise InspectorUnavailable(
            "reading a figure needs the desktop extra, which supplies the "
            "image and PDF decoders: pip install 'makeyourtree[studio]'. "
            "The question-and-answer guide works without it.")
    try:
        return handler(target)
    except FigureError:
        raise
    except Exception as exc:
        raise FigureError(f"could not read {os.path.basename(target)}: {exc}") from exc

# SPDX-License-Identifier: MIT
"""The backend-agnostic display list.

A :class:`Scene` is a plain data description of a finished figure.  It is
produced once by the compositor and then consumed by whichever backend is
asked for: the pure-Python SVG writer (no Qt, works headless and in CI) or the
Qt painter used by the interactive canvas.  Because both consume the identical
Scene, what you see on screen and what you export cannot drift apart.

Marks carry no behaviour beyond geometry and paint.  Anything that needs to
know about trees belongs in the compositor, not here.

Batching
--------
:class:`LinesMark` and :class:`RectsMark` exist for the performance-critical
case: a 100 000-leaf tree has ~400 000 branch segments that share a handful of
pens.  Emitting one mark per segment would be hopeless; the compositor groups
by paint and emits a few batched marks instead.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..style.color import Color, TRANSPARENT

__all__ = [
    "Layer", "Cap", "Join", "Anchor", "Baseline", "Paint", "TextStyle",
    "Mark", "PathMark", "LinesMark", "PolylineMark", "PolygonMark", "RectMark",
    "RectsMark", "EllipseMark", "TextMark", "ImageMark", "GroupMark",
    "Path", "Scene", "MarkSink",
]


class Layer(str, enum.Enum):
    """Painting order, back to front.  Frozen -- tracks that need a different
    layer declare it explicitly and justify it in their module docstring."""

    UNDERLAY = "underlay"
    """Clade highlight fills.  Painted first so branch lines stay legible."""
    GRID = "grid"
    CONNECTIONS = "connections"
    """Curved links between arbitrary nodes: above the background, below branches."""
    BRANCHES = "branches"
    COLLAPSED = "collapsed"
    TRACKS = "tracks"
    LABELS = "labels"
    DECOR = "decor"
    """Scale bar, axis, node symbols, support values."""
    OVERLAY = "overlay"
    """Selection, hover, rubber band -- interactive only, never exported."""
    LEGEND = "legend"

    @classmethod
    def order(cls) -> tuple["Layer", ...]:
        return (cls.UNDERLAY, cls.GRID, cls.CONNECTIONS, cls.BRANCHES,
                cls.COLLAPSED, cls.TRACKS, cls.LABELS, cls.DECOR,
                cls.OVERLAY, cls.LEGEND)


class Cap(str, enum.Enum):
    BUTT = "butt"
    ROUND = "round"
    SQUARE = "square"


class Join(str, enum.Enum):
    MITER = "miter"
    ROUND = "round"
    BEVEL = "bevel"


class Anchor(str, enum.Enum):
    """Horizontal text alignment relative to the anchor point."""

    START = "start"
    MIDDLE = "middle"
    END = "end"


class Baseline(str, enum.Enum):
    """Vertical text alignment relative to the anchor point."""

    ALPHABETIC = "alphabetic"
    MIDDLE = "middle"
    HANGING = "hanging"


@dataclass(frozen=True, slots=True)
class Paint:
    """Fill and stroke for a mark.

    ``dash`` is a sequence of on/off lengths in scene units, matching SVG's
    ``stroke-dasharray`` and Qt's dash pattern (which is in pen widths -- the
    Qt backend divides by ``width`` at the boundary).
    """

    fill: Color | None = None
    stroke: Color | None = None
    width: float = 1.0
    dash: tuple[float, ...] | None = None
    cap: Cap = Cap.BUTT
    join: Join = Join.MITER
    opacity: float = 1.0
    cosmetic: bool = False
    """Stroke keeps a constant on-screen width regardless of zoom.  Honoured by
    the Qt backend; ignored by SVG, where zoom is not a concept."""

    @staticmethod
    def stroked(color: Color, width: float = 1.0, **kw) -> "Paint":
        return Paint(fill=None, stroke=color, width=width, **kw)

    @staticmethod
    def filled(color: Color, **kw) -> "Paint":
        return Paint(fill=color, stroke=None, **kw)

    @property
    def is_visible(self) -> bool:
        if self.opacity <= 0:
            return False
        has_fill = self.fill is not None and self.fill.a > 0
        has_stroke = (self.stroke is not None and self.stroke.a > 0 and self.width > 0)
        return has_fill or has_stroke


@dataclass(frozen=True, slots=True)
class TextStyle:
    family: str = "Inter, Segoe UI, DejaVu Sans, sans-serif"
    size: float = 11.0
    weight: int = 400
    italic: bool = False
    color: Color = Color(24, 24, 27)
    anchor: Anchor = Anchor.START
    baseline: Baseline = Baseline.MIDDLE
    letter_spacing: float = 0.0
    opacity: float = 1.0


# --------------------------------------------------------------------- paths

# Path segments are tuples whose first element is an op code:
#   ("M", x, y)                          move to
#   ("L", x, y)                          line to
#   ("Q", cx, cy, x, y)                  quadratic bezier
#   ("C", c1x, c1y, c2x, c2y, x, y)      cubic bezier
#   ("A", cx, cy, r, a0, a1, ccw)        circular arc, CENTRE parameterised,
#                                        angles in DEGREES, ccw a bool
#   ("Z",)                               close
#
# Centre parameterisation is used because every arc we draw comes from polar
# layout, where the centre and the two angles are what we actually have.  The
# SVG writer converts to endpoint parameterisation; Qt consumes it directly.
Segment = tuple


class Path:
    """A mutable path builder producing a tuple of segments."""

    __slots__ = ("segments",)

    def __init__(self, segments: Iterable[Segment] | None = None) -> None:
        self.segments: list[Segment] = list(segments) if segments else []

    def move_to(self, x: float, y: float) -> "Path":
        self.segments.append(("M", x, y))
        return self

    def line_to(self, x: float, y: float) -> "Path":
        self.segments.append(("L", x, y))
        return self

    def quad_to(self, cx: float, cy: float, x: float, y: float) -> "Path":
        self.segments.append(("Q", cx, cy, x, y))
        return self

    def cubic_to(self, c1x: float, c1y: float, c2x: float, c2y: float,
                 x: float, y: float) -> "Path":
        self.segments.append(("C", c1x, c1y, c2x, c2y, x, y))
        return self

    def arc(self, cx: float, cy: float, r: float, a0: float, a1: float,
            ccw: bool = False) -> "Path":
        """Arc of radius *r* about (*cx*, *cy*) from *a0* to *a1*, in degrees."""
        self.segments.append(("A", cx, cy, r, a0, a1, ccw))
        return self

    def close(self) -> "Path":
        self.segments.append(("Z",))
        return self

    def extend(self, other: "Path") -> "Path":
        self.segments.extend(other.segments)
        return self

    def freeze(self) -> tuple[Segment, ...]:
        return tuple(self.segments)

    def __bool__(self) -> bool:
        return bool(self.segments)

    def __len__(self) -> int:
        return len(self.segments)


# --------------------------------------------------------------------- marks


@dataclass(frozen=True, slots=True)
class Mark:
    """Base for every drawable.  ``tag`` lets the canvas map a mark back to a
    node id for hit-testing and highlighting; ``None`` means undecorated."""

    paint: Paint = field(default_factory=Paint)
    tag: int | None = None


@dataclass(frozen=True, slots=True)
class PathMark(Mark):
    segments: tuple[Segment, ...] = ()


@dataclass(frozen=True, slots=True)
class LinesMark(Mark):
    """A batch of independent line segments sharing one paint.

    ``coords`` is a flat sequence ``x0, y0, x1, y1, x0, y0, x1, y1, ...``.  Flat
    rather than nested so it can be handed to ``QPainter.drawLines`` or a numpy
    buffer without repacking.
    """

    coords: Sequence[float] = ()

    @property
    def count(self) -> int:
        return len(self.coords) // 4


@dataclass(frozen=True, slots=True)
class PolylineMark(Mark):
    """One open polyline.  ``points`` is flat: ``x0, y0, x1, y1, ...``."""

    points: Sequence[float] = ()


@dataclass(frozen=True, slots=True)
class PolygonMark(Mark):
    """One closed polygon.  ``points`` is flat and need not repeat the first point."""

    points: Sequence[float] = ()


@dataclass(frozen=True, slots=True)
class RectMark(Mark):
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    rx: float = 0.0
    """Corner radius; 0 is square."""


@dataclass(frozen=True, slots=True)
class RectsMark(Mark):
    """A batch of axis-aligned rectangles sharing one paint but NOT one colour.

    ``coords`` is flat ``x, y, w, h, ...``.  ``fills`` is an optional per-rect
    colour list -- this is what makes a 200-column heatmap a single mark.
    """

    coords: Sequence[float] = ()
    fills: Sequence[Color] | None = None

    @property
    def count(self) -> int:
        return len(self.coords) // 4


@dataclass(frozen=True, slots=True)
class EllipseMark(Mark):
    cx: float = 0.0
    cy: float = 0.0
    rx: float = 0.0
    ry: float = 0.0


@dataclass(frozen=True, slots=True)
class TextMark(Mark):
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    style: TextStyle = field(default_factory=TextStyle)
    rotation: float = 0.0
    """Degrees, clockwise, about (``x``, ``y``)."""
    max_width: float | None = None
    """Advisory: backends may ellipsise to this width."""


@dataclass(frozen=True, slots=True)
class ImageMark(Mark):
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    data: bytes = b""
    """Raw encoded image bytes (PNG or JPEG)."""
    mime: str = "image/png"
    rotation: float = 0.0


@dataclass(frozen=True, slots=True)
class GroupMark(Mark):
    """Marks sharing a translation and an optional clip.  Used sparingly --
    the compositor prefers to bake transforms into coordinates."""

    marks: tuple[Mark, ...] = ()
    dx: float = 0.0
    dy: float = 0.0
    clip: tuple[float, float, float, float] | None = None


# --------------------------------------------------------------------- scene


class MarkSink:
    """Where tracks and the compositor push marks.

    A thin wrapper over the scene's layer lists that remembers a default layer,
    so a track can call ``sink.add(mark)`` without repeating its layer on every
    call while still being able to override it for a specific mark.
    """

    __slots__ = ("scene", "default_layer")

    def __init__(self, scene: "Scene", default_layer: Layer = Layer.TRACKS) -> None:
        self.scene = scene
        self.default_layer = default_layer

    def add(self, mark: Mark, layer: Layer | None = None) -> None:
        self.scene.add(mark, layer or self.default_layer)

    def extend(self, marks: Iterable[Mark], layer: Layer | None = None) -> None:
        lay = layer or self.default_layer
        for m in marks:
            self.scene.add(m, lay)

    def sub(self, layer: Layer) -> "MarkSink":
        return MarkSink(self.scene, layer)


@dataclass(slots=True)
class Scene:
    """A complete figure: sized, layered, ready for any backend."""

    width: float = 0.0
    height: float = 0.0
    background: Color = TRANSPARENT
    layers: dict[Layer, list[Mark]] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def add(self, mark: Mark, layer: Layer = Layer.BRANCHES) -> Mark:
        self.layers.setdefault(layer, []).append(mark)
        return mark

    def sink(self, layer: Layer = Layer.TRACKS) -> MarkSink:
        return MarkSink(self, layer)

    def iter_marks(self, include_overlay: bool = False) -> Iterable[Mark]:
        """All marks in painting order."""
        for lay in Layer.order():
            if lay is Layer.OVERLAY and not include_overlay:
                continue
            yield from self.layers.get(lay, ())

    def count(self) -> int:
        return sum(len(v) for v in self.layers.values())

    def clear(self, layer: Layer | None = None) -> None:
        if layer is None:
            self.layers.clear()
        else:
            self.layers.pop(layer, None)

    def __repr__(self) -> str:
        parts = ", ".join(f"{k.value}={len(v)}" for k, v in self.layers.items() if v)
        return f"<Scene {self.width:g}x{self.height:g} {parts}>"

# SPDX-License-Identifier: MIT
"""The annotation track contract.

A track is a strip of data drawn alongside the tree: a colour band per tip, a
heatmap, bars, pies, domain diagrams.  Tracks stack outward from the tree and
each one declares how much room it needs before anything is drawn, so the
compositor can lay them out in one pass.

Writing a track
---------------
Subclass :class:`Track`, set ``type_id`` and ``display_name``, and implement
:meth:`Track.measure` and :meth:`Track.draw`.  Draw exclusively through
``ctx.projector`` in band-space ``(row, offset)`` coordinates -- never in scene
coordinates.  Do that and the track works in rectangular, slanted, circular and
radial layouts with no further effort, because the projector supplies the
mapping (see :mod:`makeyourtree.layout.projector`).

The two-phase protocol matters: ``measure`` is called for every track first,
offsets are accumulated, and only then is ``draw`` called with a context whose
``offset`` is final.  ``measure`` must therefore be pure.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable, Sequence

from ..core.diagnostics import DiagnosticSink
from ..core.tree import Tree
from ..layout.frame import LayoutFrame
from ..layout.projector import Projector
from ..scene.marks import Layer, MarkSink
from ..style.color import Color
from ..style.theme import Theme
from ..text.metrics import TextMetrics

__all__ = [
    "TrackData", "TrackContext", "LegendItem", "Legend", "Track",
    "register", "get_track_class", "track_types",
]


# --------------------------------------------------------------------- data


@dataclass(slots=True)
class TrackData:
    """Values bound to nodes.

    Binding happens once, when an annotation table is attached to a tree: the
    text keys in the file are resolved to node ids, and everything downstream
    works with ids.  Re-binding is only needed if the tree gains or loses nodes.
    """

    columns: list[str] = field(default_factory=list)
    """Column headers, in order.  Single-value tracks have exactly one."""
    rows: dict[int, list[Any]] = field(default_factory=dict)
    """node id -> one value per column.  Missing entries mean "no data here",
    which every track must render as a gap rather than as zero."""
    unmatched: list[str] = field(default_factory=list)
    """Keys present in the source that matched no node.  Surfaced to the user
    rather than silently dropped -- a 90 % unmatched file is a user error worth
    reporting, not an empty track."""
    source: str | None = None

    def get(self, node_id: int, column: int = 0, default: Any = None) -> Any:
        row = self.rows.get(node_id)
        if row is None or column >= len(row):
            return default
        v = row[column]
        return default if v is None else v

    def numeric_column(self, column: int = 0) -> list[float]:
        """Every finite numeric value in a column, for range computation."""
        import math
        out: list[float] = []
        for row in self.rows.values():
            if column >= len(row):
                continue
            v = row[column]
            if v is None:
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(f):
                out.append(f)
        return out

    def value_range(self, column: int | None = None) -> tuple[float, float] | None:
        """(min, max) over one column, or over all columns when *column* is None."""
        vals: list[float] = []
        cols = range(len(self.columns)) if column is None else [column]
        for c in cols:
            vals.extend(self.numeric_column(c))
        if not vals:
            return None
        return (min(vals), max(vals))

    def categories(self, column: int = 0) -> list[str]:
        """Distinct non-empty string values in a column, in first-seen order."""
        seen: dict[str, None] = {}
        for row in self.rows.values():
            if column < len(row) and row[column] not in (None, ""):
                seen.setdefault(str(row[column]), None)
        return list(seen)

    def __len__(self) -> int:
        return len(self.rows)


# ------------------------------------------------------------------ context


@dataclass(slots=True)
class TrackContext:
    """Everything a track needs in order to measure or draw itself."""

    tree: Tree
    frame: LayoutFrame
    projector: Projector
    theme: Theme
    metrics: TextMetrics
    offset: float = 0.0
    """Band-space offset at which this track starts.  Final only in ``draw``."""
    index: int = 0
    """Position of this track in the stack, for alternating shading etc."""
    interactive: bool = False
    """True on the canvas, false when exporting.  Tracks may add hover affordances
    only when true."""
    sink: DiagnosticSink | None = None

    def rows_of(self, node_id: int) -> tuple[float, float]:
        return self.frame.row_span(node_id)

    def tip_ids(self) -> list[int]:
        return self.frame.tips

    def warn(self, code: str, message: str) -> None:
        if self.sink is not None:
            self.sink.warn(code, message)


# ------------------------------------------------------------------- legend


@dataclass(frozen=True, slots=True)
class LegendItem:
    label: str
    color: Color | None = None
    shape: str = "square"
    """``square``, ``circle``, ``line``, ``gradient``, or any registered shape."""
    gradient: tuple[Color, ...] | None = None
    value_range: tuple[float, float] | None = None


@dataclass(slots=True)
class Legend:
    title: str = ""
    items: list[LegendItem] = field(default_factory=list)
    kind: str = "categorical"
    """``categorical``, ``continuous``, or ``scale``."""

    def __bool__(self) -> bool:
        return bool(self.items)


# -------------------------------------------------------------------- track


class Track(abc.ABC):
    """Base class for every annotation track."""

    type_id: ClassVar[str] = ""
    """Stable identifier used in project files.  Never rename one in place."""
    display_name: ClassVar[str] = ""
    default_layer: ClassVar[Layer] = Layer.TRACKS
    needs_numeric: ClassVar[bool] = False
    multi_column: ClassVar[bool] = False
    """True when the track consumes every column rather than just the first."""

    _counter: ClassVar[int] = 0

    def __init__(self, *, id: str = "", title: str = "",
                 data: TrackData | None = None,
                 options: dict[str, Any] | None = None) -> None:
        # `id` shadows the builtin here, so generate the fallback from a class
        # counter rather than from id(self).
        Track._counter += 1
        self.id = id or f"{self.type_id}-{Track._counter:04d}"
        self.title = title
        self.data = data if data is not None else TrackData()
        self.options: dict[str, Any] = dict(self.default_options())
        if options:
            self.options.update(options)
        self.visible = True
        self.collapsed_in_ui = False

    # ---------------------------------------------------------- options

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        """Option defaults for this track type.  Subclasses extend this dict."""
        return {
            "thickness": 22.0,
            "gap_before": None,
            "show_title": True,
            "border_width": 0.0,
            "border_color": None,
            "opacity": 1.0,
        }

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    # ----------------------------------------------------------- protocol

    @abc.abstractmethod
    def measure(self, ctx: TrackContext) -> float:
        """Band-space thickness this track needs.  Must not mutate anything."""

    @abc.abstractmethod
    def draw(self, ctx: TrackContext, sink: MarkSink) -> None:
        """Emit marks.  ``ctx.offset`` is the final band-space start offset."""

    def legend(self) -> Legend:
        """Legend entries for this track.  Empty legend means "contributes none"."""
        return Legend(title=self.title)

    # ------------------------------------------------------------ binding

    def bind(self, tree: Tree, keys_to_values: dict[str, Sequence[Any]], *,
             columns: Sequence[str] | None = None,
             match_internal: bool = True,
             sink: DiagnosticSink | None = None) -> None:
        """Resolve text keys to node ids and populate :attr:`data`.

        A key matches a node name; when *match_internal* is false only leaves
        are considered.  Keys that match nothing are recorded in
        ``data.unmatched`` so the UI can report them.
        """
        by_name: dict[str, list[int]] = {}
        for n in tree.nodes:
            if not n.name:
                continue
            if not match_internal and n.children:
                continue
            by_name.setdefault(n.name, []).append(n.id)

        rows: dict[int, list[Any]] = {}
        unmatched: list[str] = []
        for key, vals in keys_to_values.items():
            ids = by_name.get(key)
            if not ids:
                unmatched.append(key)
                continue
            for nid in ids:
                rows[nid] = list(vals)
        self.data = TrackData(
            columns=list(columns) if columns is not None else list(self.data.columns),
            rows=rows, unmatched=unmatched, source=self.data.source,
        )
        if unmatched and sink is not None:
            shown = ", ".join(unmatched[:5])
            more = f" (+{len(unmatched) - 5} more)" if len(unmatched) > 5 else ""
            sink.warn("track.unmatched",
                      f"{self.display_name or self.type_id} '{self.title}': "
                      f"{len(unmatched)} key(s) matched no node: {shown}{more}")

    # ------------------------------------------------------ serialisation

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_id,
            "id": self.id,
            "title": self.title,
            "visible": self.visible,
            "options": _jsonable(self.options),
            "columns": list(self.data.columns),
            "rows": {str(k): _jsonable(v) for k, v in self.data.rows.items()},
            "source": self.data.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Track":
        klass = get_track_class(d["type"])
        data = TrackData(
            columns=list(d.get("columns", [])),
            rows={int(k): list(v) for k, v in (d.get("rows") or {}).items()},
            source=d.get("source"),
        )
        t = klass(id=d.get("id", ""), title=d.get("title", ""),
                  data=data, options=d.get("options") or {})
        t.visible = bool(d.get("visible", True))
        return t

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.title!r} rows={len(self.data)}>"


def _jsonable(v: Any) -> Any:
    if isinstance(v, Color):
        return v.hex
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


# ----------------------------------------------------------------- registry

_REGISTRY: dict[str, type[Track]] = {}


def register(klass: type[Track]) -> type[Track]:
    """Class decorator adding a track type to the registry."""
    if not klass.type_id:
        raise ValueError(f"{klass.__name__} must define type_id")
    if klass.type_id in _REGISTRY and _REGISTRY[klass.type_id] is not klass:
        raise ValueError(f"duplicate track type_id {klass.type_id!r}")
    _REGISTRY[klass.type_id] = klass
    return klass


def get_track_class(type_id: str) -> type[Track]:
    try:
        return _REGISTRY[type_id]
    except KeyError:
        raise KeyError(f"unknown track type {type_id!r}; "
                       f"known: {', '.join(sorted(_REGISTRY))}") from None


def track_types() -> list[type[Track]]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]

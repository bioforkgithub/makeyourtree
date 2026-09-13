# SPDX-License-Identifier: MIT
"""The renderer contract.

One :class:`Scene`, several output devices: the pure-Python SVG writer in
:mod:`makeyourtree.render.svg`, the Qt painter behind the interactive canvas, and
whatever raster exporter sits on top of them.  They all implement
:class:`RenderBackend`, and :func:`render` is the single walker that drives
them.  Because there is exactly one walker, layer order, overlay suppression
and mark dispatch cannot drift between "what you see" and "what you export" --
that divergence is the classic failure mode of tools that grow a second,
export-only drawing path.

A backend implements one method per concrete mark type.  Dispatch is a table
lookup on the mark's exact class, so adding a mark type is a compile-time-ish
error (``RenderError``) rather than a silently skipped drawable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.errors import RenderError
from ..scene.marks import (EllipseMark, GroupMark, ImageMark, Layer, LinesMark,
                           Mark, PathMark, PolygonMark, PolylineMark, RectMark,
                           RectsMark, Scene, TextMark)

__all__ = ["RenderBackend", "render", "dispatch_mark", "DISPATCH"]


@runtime_checkable
class RenderBackend(Protocol):
    """What a device must provide to consume a :class:`Scene`.

    ``begin_layer`` / ``end_layer`` are optional: :func:`render` calls them only
    when the backend defines them, so a minimal backend (a test double, a
    hit-test collector) needs just ``begin``, ``end`` and the draw methods.
    """

    def begin(self, scene: Scene) -> None:
        """Prepare for a new scene: page size, background, reset state."""
        ...

    def end(self) -> bytes:
        """Finish and return the encoded document.  Empty for live painters."""
        ...

    def begin_layer(self, layer: Layer) -> None: ...

    def end_layer(self, layer: Layer) -> None: ...

    def draw_path(self, mark: PathMark) -> None: ...

    def draw_lines(self, mark: LinesMark) -> None: ...

    def draw_polyline(self, mark: PolylineMark) -> None: ...

    def draw_polygon(self, mark: PolygonMark) -> None: ...

    def draw_rect(self, mark: RectMark) -> None: ...

    def draw_rects(self, mark: RectsMark) -> None: ...

    def draw_ellipse(self, mark: EllipseMark) -> None: ...

    def draw_text(self, mark: TextMark) -> None: ...

    def draw_image(self, mark: ImageMark) -> None: ...

    def draw_group(self, mark: GroupMark) -> None: ...


DISPATCH: dict[type, str] = {
    PathMark: "draw_path",
    LinesMark: "draw_lines",
    PolylineMark: "draw_polyline",
    PolygonMark: "draw_polygon",
    RectMark: "draw_rect",
    RectsMark: "draw_rects",
    EllipseMark: "draw_ellipse",
    TextMark: "draw_text",
    ImageMark: "draw_image",
    GroupMark: "draw_group",
}
"""Mark class -> backend method name.  Exact-class keyed; see :func:`dispatch_mark`."""


def dispatch_mark(backend: RenderBackend, mark: Mark) -> None:
    """Send one mark to its handler.

    Exported because :class:`GroupMark` handlers need it to draw their children
    without re-implementing the table.
    """
    method = DISPATCH.get(type(mark))
    if method is None:
        # A subclass of a known mark type is still drawable as its base.
        for klass, name in DISPATCH.items():
            if isinstance(mark, klass):
                method = name
                break
    if method is None:
        raise RenderError(f"no backend handler for mark type {type(mark).__name__}")
    getattr(backend, method)(mark)


def render(scene: Scene, backend: RenderBackend, *,
           include_overlay: bool = False) -> bytes:
    """Walk *scene* in painting order and drive *backend*.

    ``Layer.OVERLAY`` holds selection and hover affordances that exist only on
    the live canvas; it is skipped unless *include_overlay* is set, which is
    what keeps an export free of transient interaction state.
    """
    backend.begin(scene)
    begin_layer = getattr(backend, "begin_layer", None)
    end_layer = getattr(backend, "end_layer", None)
    for layer in Layer.order():
        if layer is Layer.OVERLAY and not include_overlay:
            continue
        marks = scene.layers.get(layer)
        if not marks:
            continue
        if begin_layer is not None:
            begin_layer(layer)
        for mark in marks:
            dispatch_mark(backend, mark)
        if end_layer is not None:
            end_layer(layer)
    return backend.end()

# SPDX-License-Identifier: MIT
"""Shared helpers for the compositor, legend, backend and CLI tests.

Trees are built directly from :class:`~makeyourtree.core.node.Node` rather than
parsed, so these tests exercise the compositor and the renderers without
depending on the file readers.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET


from makeyourtree.core.tree import Tree
from makeyourtree.doc.document import Document
from makeyourtree.layout.params import LayoutParams
from makeyourtree.scene.marks import (EllipseMark, GroupMark, ImageMark, Layer,
                                  LinesMark, Mark, PathMark, PolygonMark,
                                  PolylineMark, RectMark, RectsMark, TextMark)
from makeyourtree.style.theme import Theme

SVG_NS = "{http://www.w3.org/2000/svg}"


def build_tree() -> Tree:
    """A small balanced tree with names and branch lengths on every edge."""
    tree = Tree()
    tree.root.name = "root"

    def add(parent, name, length, support=None):
        node = tree.new_node(name, length, support)
        parent.add_child(node)
        return node

    left = add(tree.root, "clade_left", 0.3, 88.0)
    right = add(tree.root, "clade_right", 0.6, 61.0)
    add(left, "Alphaproteobacteria sp.", 0.10)
    add(left, "Betavirus", 0.20)
    add(right, "Gammaphage", 0.40)
    add(right, "Deltamonas", 0.55)
    tree.refresh()
    return tree


def caterpillar(n_leaves: int) -> Tree:
    """A maximally unbalanced tree: the shape that breaks recursive code."""
    tree = Tree()
    tree.root.name = "root"
    cursor = tree.root
    for i in range(n_leaves - 1):
        leaf = tree.new_node(f"t{i}", 0.05)
        cursor.add_child(leaf)
        nxt = tree.new_node(None, 0.05)
        cursor.add_child(nxt)
        cursor = nxt
    last = tree.new_node(f"t{n_leaves - 1}", 0.05)
    cursor.add_child(last)
    tree.refresh()
    return tree


def make_document(tree: Tree | None = None, *, theme: Theme | None = None,
                  **params) -> Document:
    return Document(tree=tree if tree is not None else build_tree(),
                    params=LayoutParams(**params),
                    theme=theme if theme is not None else Theme())


class RecordingBackend:
    """Minimal backend that records the calls :func:`render` makes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Mark]] = []
        self.layers: list[Layer] = []
        self.began: int = 0

    def begin(self, scene) -> None:
        self.began += 1
        self.scene = scene

    def end(self) -> bytes:
        return b"done"

    def begin_layer(self, layer: Layer) -> None:
        self.layers.append(layer)

    def end_layer(self, layer: Layer) -> None:
        pass

    def _record(self, name):
        def handler(mark):
            self.calls.append((name, mark))
        return handler

    def __getattr__(self, name):
        if name.startswith("draw_"):
            return self._record(name)
        raise AttributeError(name)


# --------------------------------------------------------------- assertions


def parse_svg(text: str) -> ET.Element:
    """Parse an SVG document, failing the test if it is not well-formed XML."""
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:  # pragma: no cover - only on a real failure
        raise AssertionError(f"rendered SVG is not valid XML: {exc}\n{text[:800]}")


def geometric_bounds(scene) -> tuple[float, float, float, float]:
    """Extent of every non-text mark, computed independently of the compositor.

    Text is excluded on purpose: this is the cross-check that the compositor's
    own bounds calculation is not simply trusted.
    """
    x0 = y0 = math.inf
    x1 = y1 = -math.inf

    def visit(mark: Mark, dx: float, dy: float) -> None:
        nonlocal x0, y0, x1, y1
        xs: list[float] = []
        ys: list[float] = []
        if isinstance(mark, LinesMark):
            xs = list(mark.coords[0::2])
            ys = list(mark.coords[1::2])
        elif isinstance(mark, (PolygonMark, PolylineMark)):
            xs = list(mark.points[0::2])
            ys = list(mark.points[1::2])
        elif isinstance(mark, RectMark):
            xs = [mark.x, mark.x + mark.w]
            ys = [mark.y, mark.y + mark.h]
        elif isinstance(mark, RectsMark):
            c = mark.coords
            for i in range(0, len(c) - 3, 4):
                xs.extend((c[i], c[i] + c[i + 2]))
                ys.extend((c[i + 1], c[i + 1] + c[i + 3]))
        elif isinstance(mark, EllipseMark):
            xs = [mark.cx - mark.rx, mark.cx + mark.rx]
            ys = [mark.cy - mark.ry, mark.cy + mark.ry]
        elif isinstance(mark, ImageMark):
            xs = [mark.x, mark.x + mark.w]
            ys = [mark.y, mark.y + mark.h]
        elif isinstance(mark, PathMark):
            for seg in mark.segments:
                if seg[0] in ("M", "L"):
                    xs.append(seg[1])
                    ys.append(seg[2])
                elif seg[0] == "A":
                    xs.extend((seg[1] - seg[3], seg[1] + seg[3]))
                    ys.extend((seg[2] - seg[3], seg[2] + seg[3]))
        elif isinstance(mark, GroupMark):
            for child in mark.marks:
                visit(child, dx + mark.dx, dy + mark.dy)
            return
        elif isinstance(mark, TextMark):
            return
        for x in xs:
            x0 = min(x0, x + dx)
            x1 = max(x1, x + dx)
        for y in ys:
            y0 = min(y0, y + dy)
            y1 = max(y1, y + dy)

    for mark in scene.iter_marks(include_overlay=False):
        visit(mark, 0.0, 0.0)
    if x0 > x1:
        return (0.0, 0.0, 0.0, 0.0)
    return (x0, y0, x1, y1)

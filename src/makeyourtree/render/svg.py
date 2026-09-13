# SPDX-License-Identifier: MIT
"""SVG 1.1 writer.

Pure Python: no Qt, no external library, so it runs in CI, in a headless
container and inside the CLI.  The output is deliberately plain -- one element
per mark, one ``<g>`` per layer, attributes rather than a stylesheet -- because
the files are meant to be opened in a vector editor and hand-edited afterwards,
and because a diffable export is worth more than a slightly smaller one.

Arc conversion
--------------
:class:`~makeyourtree.scene.marks.Path` stores circular arcs **centre
parameterised** ``(cx, cy, r, a0, a1, ccw)``, which is what polar layout
actually computes.  SVG's ``A`` command is **endpoint parameterised**: it takes
the destination point plus two flags that pick one of the four arcs joining the
current point to it.  The conversion follows the SVG 1.1 implementation notes
(appendix F.6, "elliptical arc implementation notes"):

* ``sweep-flag`` is 1 when the angle increases.  Scene space has y growing
  downward, so an increasing angle sweeps clockwise on screen, which is exactly
  what ``sweep-flag = 1`` means there.
* ``large-arc-flag`` is 1 when the swept angle exceeds 180 degrees.
* A single ``A`` cannot express a full turn: start and end coincide, the two
  candidate arcs degenerate, and every renderer draws nothing.  A closed ring is
  therefore split into two half turns.
"""

from __future__ import annotations

import base64
import math
from typing import Any, Iterable, Sequence

from ..scene.marks import (Anchor, Baseline, Cap, EllipseMark, GroupMark,
                           ImageMark, Join, Layer, LinesMark, Paint, PathMark,
                           PolygonMark, PolylineMark, RectMark, RectsMark,
                           Scene, TextMark)
from ..style.color import Color
from .backend import dispatch_mark, render

__all__ = ["SvgBackend", "render_svg"]

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"

# Angles closer than this to a whole turn are treated as a whole turn.  Polar
# layouts routinely produce 359.9999... from accumulated float error.
_FULL_TURN_EPS = 1e-6
_POINT_EPS = 1e-9

_ANCHOR = {Anchor.START: "start", Anchor.MIDDLE: "middle", Anchor.END: "end"}
_BASELINE = {Baseline.MIDDLE: "central", Baseline.HANGING: "hanging"}


def _esc_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(s: str) -> str:
    return _esc_text(s).replace('"', "&quot;")


class _Num:
    """Fixed-precision number formatter.

    Trailing zeros are stripped so coordinates survive a text diff cleanly and
    a large export does not carry six redundant decimal digits per number.
    """

    __slots__ = ("nd",)

    def __init__(self, nd: int) -> None:
        self.nd = max(0, int(nd))

    def __call__(self, v: float) -> str:
        f = float(v)
        if not math.isfinite(f):
            f = 0.0
        s = f"{f:.{self.nd}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return "0" if s in ("", "-", "-0") else s


class SvgBackend:
    """Serialises a :class:`Scene` into an SVG 1.1 document."""

    def __init__(self, *, precision: int = 3, title: str | None = None,
                 description: str | None = None,
                 class_prefix: str = "makeyourtree-",
                 units: str = "pt") -> None:
        self.precision = precision
        self.title = title
        self.description = description
        self.class_prefix = class_prefix
        self.units = units
        self._n = _Num(precision)
        self._body: list[str] = []
        self._defs: list[str] = []
        self._head: list[str] = []
        self._clip_seq = 0
        self._open_layer: Layer | None = None

    # ------------------------------------------------------------ lifecycle

    def begin(self, scene: Scene) -> None:
        n = self._n
        self._body = []
        self._defs = []
        self._head = []
        self._clip_seq = 0
        w, h = max(0.0, scene.width), max(0.0, scene.height)
        # The viewBox stays unitless -- it is the user-coordinate system the
        # marks are drawn in -- while width/height carry a physical unit, so a
        # consumer places the figure at its true size. Without the unit an SVG
        # length is a CSS pixel (1/96 in) while a scene unit is a point
        # (1/72 in), which made an SVG import 25% smaller than the same figure
        # as PDF. See makeyourtree.render.sizing.
        unit = self.units or ""
        self._head.append(
            '<svg xmlns="{ns}" xmlns:xlink="{xl}" version="1.1" '
            'width="{w}{u}" height="{h}{u}" viewBox="0 0 {w} {h}">'.format(
                ns=_SVG_NS, xl=_XLINK_NS, w=n(w), h=n(h), u=unit)
        )
        if self.title:
            self._head.append("<title>" + _esc_text(self.title) + "</title>")
        if self.description:
            self._head.append("<desc>" + _esc_text(self.description) + "</desc>")
        bg = scene.background
        if bg is not None and bg.a > 0:
            attrs = {"x": "0", "y": "0", "width": n(w), "height": n(h),
                     "fill": bg.rgb_hex}
            if bg.a < 255:
                attrs["fill-opacity"] = n(bg.opacity)
            self._head.append(self._tag("rect", attrs, cls="background"))

    def end(self) -> bytes:
        self._close_layer()
        parts = list(self._head)
        if self._defs:
            parts.append("<defs>")
            parts.extend(self._defs)
            parts.append("</defs>")
        parts.extend(self._body)
        parts.append("</svg>")
        return ("\n".join(parts) + "\n").encode("utf-8")

    @property
    def svg(self) -> str:
        return self.end().decode("utf-8")

    def begin_layer(self, layer: Layer) -> None:
        self._close_layer()
        self._body.append('<g class="' + self.class_prefix + layer.value + '">')
        self._open_layer = layer

    def end_layer(self, layer: Layer) -> None:
        self._close_layer()

    def _close_layer(self) -> None:
        if self._open_layer is not None:
            self._body.append("</g>")
            self._open_layer = None

    # ------------------------------------------------------------- plumbing

    def _tag(self, name: str, attrs: dict[str, str], *, cls: str | None = None,
             body: str | None = None) -> str:
        if cls:
            attrs = dict({"class": self.class_prefix + cls}, **attrs)
        rendered = " ".join(
            k + '="' + _esc_attr(v) + '"' for k, v in attrs.items() if v is not None)
        if body is None:
            return "<" + name + (" " + rendered if rendered else "") + "/>"
        head = "<" + name + (" " + rendered if rendered else "") + ">"
        return head + body + "</" + name + ">"

    def _emit(self, s: str) -> None:
        self._body.append(s)

    def _paint_attrs(self, p: Paint, *, fill_override: Color | None = None,
                     want_fill: bool = True,
                     want_stroke: bool = True) -> dict[str, str]:
        """SVG presentation attributes for a :class:`Paint`.

        ``Paint.opacity`` multiplies into the per-channel opacities rather than
        becoming a group ``opacity``, so overlapping strokes inside one batched
        mark composite the way the canvas paints them.
        """
        n = self._n
        out: dict[str, str] = {}
        if want_fill:
            fill = fill_override if fill_override is not None else p.fill
            if fill is not None and fill.a > 0:
                out["fill"] = fill.rgb_hex
                fo = fill.opacity * p.opacity
                if fo < 1.0:
                    out["fill-opacity"] = n(fo)
            else:
                out["fill"] = "none"
        if want_stroke:
            if p.stroke is not None and p.stroke.a > 0 and p.width > 0:
                out["stroke"] = p.stroke.rgb_hex
                out["stroke-width"] = n(p.width)
                so = p.stroke.opacity * p.opacity
                if so < 1.0:
                    out["stroke-opacity"] = n(so)
                if p.dash:
                    out["stroke-dasharray"] = ",".join(n(d) for d in p.dash)
                if p.cap is not Cap.BUTT:
                    out["stroke-linecap"] = p.cap.value
                if p.join is not Join.MITER:
                    out["stroke-linejoin"] = p.join.value
        return out

    # ----------------------------------------------------------------- marks

    def draw_path(self, mark: PathMark) -> None:
        d = self.path_data(mark.segments)
        if not d:
            return
        attrs = {"d": d}
        attrs.update(self._paint_attrs(mark.paint))
        self._emit(self._tag("path", attrs))

    def draw_lines(self, mark: LinesMark) -> None:
        c = mark.coords
        if len(c) < 4:
            return
        n = self._n
        parts: list[str] = []
        for i in range(0, len(c) - 3, 4):
            parts.append("M" + n(c[i]) + " " + n(c[i + 1])
                         + "L" + n(c[i + 2]) + " " + n(c[i + 3]))
        attrs = {"d": "".join(parts), "fill": "none"}
        attrs.update(self._paint_attrs(mark.paint, want_fill=False))
        self._emit(self._tag("path", attrs))

    def draw_polyline(self, mark: PolylineMark) -> None:
        pts = self._points(mark.points)
        if not pts:
            return
        attrs = {"points": pts}
        attrs.update(self._paint_attrs(mark.paint))
        self._emit(self._tag("polyline", attrs))

    def draw_polygon(self, mark: PolygonMark) -> None:
        pts = self._points(mark.points)
        if not pts:
            return
        attrs = {"points": pts}
        attrs.update(self._paint_attrs(mark.paint))
        self._emit(self._tag("polygon", attrs))

    def draw_rect(self, mark: RectMark) -> None:
        n = self._n
        x, y, w, h = _normalise_rect(mark.x, mark.y, mark.w, mark.h)
        attrs = {"x": n(x), "y": n(y), "width": n(w), "height": n(h)}
        if mark.rx:
            attrs["rx"] = n(mark.rx)
        attrs.update(self._paint_attrs(mark.paint))
        self._emit(self._tag("rect", attrs))

    def draw_rects(self, mark: RectsMark) -> None:
        """A batch becomes one ``<g>`` carrying the shared stroke, with the
        per-rect fill on each child.  Repeating the stroke attributes on every
        rectangle would triple the size of a wide heatmap."""
        c = mark.coords
        if len(c) < 4:
            return
        n = self._n
        fills = mark.fills
        group = self._paint_attrs(mark.paint, want_fill=fills is None)
        inner: list[str] = []
        for i in range(0, len(c) - 3, 4):
            x, y, w, h = _normalise_rect(c[i], c[i + 1], c[i + 2], c[i + 3])
            a = {"x": n(x), "y": n(y), "width": n(w), "height": n(h)}
            if fills is not None:
                idx = i // 4
                col = fills[idx] if idx < len(fills) else None
                if col is None or col.a == 0:
                    a["fill"] = "none"
                else:
                    a["fill"] = col.rgb_hex
                    fo = col.opacity * mark.paint.opacity
                    if fo < 1.0:
                        a["fill-opacity"] = n(fo)
            inner.append(self._tag("rect", a))
        self._emit(self._tag("g", group, body="".join(inner)))

    def draw_ellipse(self, mark: EllipseMark) -> None:
        n = self._n
        rx, ry = abs(mark.rx), abs(mark.ry)
        if rx <= 0 or ry <= 0:
            return
        if abs(rx - ry) <= _POINT_EPS:
            attrs = {"cx": n(mark.cx), "cy": n(mark.cy), "r": n(rx)}
            name = "circle"
        else:
            attrs = {"cx": n(mark.cx), "cy": n(mark.cy), "rx": n(rx), "ry": n(ry)}
            name = "ellipse"
        attrs.update(self._paint_attrs(mark.paint))
        self._emit(self._tag(name, attrs))

    def draw_text(self, mark: TextMark) -> None:
        if not mark.text:
            return
        n = self._n
        st = mark.style
        attrs: dict[str, str] = {"x": n(mark.x), "y": n(mark.y)}
        if mark.rotation:
            attrs["transform"] = ("rotate(" + n(mark.rotation) + " "
                                  + n(mark.x) + " " + n(mark.y) + ")")
        attrs["font-family"] = st.family
        attrs["font-size"] = n(st.size)
        if st.weight != 400:
            attrs["font-weight"] = str(int(st.weight))
        if st.italic:
            attrs["font-style"] = "italic"
        if st.letter_spacing:
            attrs["letter-spacing"] = n(st.letter_spacing)
        if st.anchor is not Anchor.START:
            attrs["text-anchor"] = _ANCHOR[st.anchor]
        baseline = _BASELINE.get(st.baseline)
        if baseline:
            attrs["dominant-baseline"] = baseline
        col = st.color
        attrs["fill"] = col.rgb_hex
        fo = col.opacity * st.opacity
        if fo < 1.0:
            attrs["fill-opacity"] = n(fo)
        self._emit(self._tag("text", attrs, body=_esc_text(mark.text)))

    def draw_image(self, mark: ImageMark) -> None:
        if not mark.data or mark.w <= 0 or mark.h <= 0:
            return
        n = self._n
        uri = ("data:" + mark.mime + ";base64,"
               + base64.b64encode(bytes(mark.data)).decode("ascii"))
        attrs = {"x": n(mark.x), "y": n(mark.y),
                 "width": n(mark.w), "height": n(mark.h)}
        if mark.rotation:
            cx, cy = mark.x + mark.w / 2.0, mark.y + mark.h / 2.0
            attrs["transform"] = ("rotate(" + n(mark.rotation) + " "
                                  + n(cx) + " " + n(cy) + ")")
        if mark.paint.opacity < 1.0:
            attrs["opacity"] = n(mark.paint.opacity)
        # Both spellings: SVG 1.1 tools want xlink:href, SVG 2 renderers href.
        attrs["href"] = uri
        attrs["xlink:href"] = uri
        self._emit(self._tag("image", attrs))

    def draw_group(self, mark: GroupMark) -> None:
        n = self._n
        attrs: dict[str, str] = {}
        if mark.dx or mark.dy:
            attrs["transform"] = "translate(" + n(mark.dx) + " " + n(mark.dy) + ")"
        if mark.clip is not None:
            self._clip_seq += 1
            cid = self.class_prefix + "clip" + str(self._clip_seq)
            cx0, cy0, cx1, cy1 = mark.clip
            x, y, w, h = _normalise_rect(cx0, cy0, cx1 - cx0, cy1 - cy0)
            self._defs.append(
                '<clipPath id="' + _esc_attr(cid) + '"><rect x="' + n(x)
                + '" y="' + n(y) + '" width="' + n(w) + '" height="' + n(h)
                + '"/></clipPath>')
            attrs["clip-path"] = "url(#" + cid + ")"
        rendered = " ".join(k + '="' + _esc_attr(v) + '"' for k, v in attrs.items())
        self._emit("<g " + rendered + ">" if rendered else "<g>")
        for child in mark.marks:
            dispatch_mark(self, child)
        self._emit("</g>")

    # ------------------------------------------------------------- geometry

    def _points(self, flat: Sequence[float]) -> str:
        n = self._n
        if len(flat) < 4:
            return ""
        return " ".join(n(flat[i]) + "," + n(flat[i + 1])
                        for i in range(0, len(flat) - 1, 2))

    def path_data(self, segments: Iterable[tuple]) -> str:
        """Serialise centre-parameterised path segments to an SVG ``d`` string."""
        n = self._n
        out: list[str] = []
        cur: tuple[float, float] | None = None
        start: tuple[float, float] | None = None
        for seg in segments:
            op = seg[0]
            if op == "M":
                cur = (seg[1], seg[2])
                start = cur
                out.append("M" + n(cur[0]) + " " + n(cur[1]))
            elif op == "L":
                cur = (seg[1], seg[2])
                out.append("L" + n(cur[0]) + " " + n(cur[1]))
            elif op == "Q":
                cur = (seg[3], seg[4])
                out.append("Q" + n(seg[1]) + " " + n(seg[2]) + " "
                           + n(cur[0]) + " " + n(cur[1]))
            elif op == "C":
                cur = (seg[5], seg[6])
                out.append("C" + n(seg[1]) + " " + n(seg[2]) + " "
                           + n(seg[3]) + " " + n(seg[4]) + " "
                           + n(cur[0]) + " " + n(cur[1]))
            elif op == "A":
                cur = self._arc(out, cur, *seg[1:])
                if start is None:
                    start = cur
            elif op == "Z":
                out.append("Z")
                cur = start
        return "".join(out)

    def _arc(self, out: list[str], cur: tuple[float, float] | None,
             cx: float, cy: float, r: float, a0: float, a1: float,
             ccw: bool = False) -> tuple[float, float]:
        """Append the ``A`` commands for one centre-parameterised arc.

        Returns the new current point.  See the module docstring for the flag
        derivation and for why a full turn needs two commands.
        """
        n = self._n
        p0 = _polar(cx, cy, r, a0)
        if cur is None:
            out.append("M" + n(p0[0]) + " " + n(p0[1]))
        elif math.hypot(cur[0] - p0[0], cur[1] - p0[1]) > _POINT_EPS:
            out.append("L" + n(p0[0]) + " " + n(p0[1]))
        if r <= 0:
            return p0

        # Signed sweep in the requested direction, folded into [0, 360).  A
        # non-zero raw sweep that folds to zero is a whole number of turns.
        raw = (a0 - a1) if ccw else (a1 - a0)
        delta = raw % 360.0
        if delta > 360.0 - _FULL_TURN_EPS or (abs(raw) > _FULL_TURN_EPS
                                              and delta < _FULL_TURN_EPS):
            delta = 360.0
        if delta <= _FULL_TURN_EPS:
            return p0

        sweep = 0 if ccw else 1
        rr = n(r) + " " + n(r) + " 0"
        if delta >= 360.0 - _FULL_TURN_EPS:
            half = -180.0 if ccw else 180.0
            mid = _polar(cx, cy, r, a0 + half)
            out.append("A" + rr + " 1 " + str(sweep) + " " + n(mid[0]) + " " + n(mid[1]))
            out.append("A" + rr + " 1 " + str(sweep) + " " + n(p0[0]) + " " + n(p0[1]))
            return p0
        p1 = _polar(cx, cy, r, a1)
        large = 1 if delta > 180.0 else 0
        out.append("A" + rr + " " + str(large) + " " + str(sweep) + " "
                   + n(p1[0]) + " " + n(p1[1]))
        return p1


def _polar(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    a = math.radians(angle_deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def _normalise_rect(x: float, y: float, w: float,
                    h: float) -> tuple[float, float, float, float]:
    """SVG rejects negative ``width``/``height``; fold them into the origin."""
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    return (x, y, w, h)


def render_svg(scene: Scene, **kw: Any) -> str:
    """Render *scene* to an SVG document string.

    Keyword arguments are the :class:`SvgBackend` options plus
    ``include_overlay``, off by default because overlay marks are interaction
    state and have no business in a file.
    """
    include_overlay = bool(kw.pop("include_overlay", False))
    backend = SvgBackend(**kw)
    return render(scene, backend, include_overlay=include_overlay).decode("utf-8")

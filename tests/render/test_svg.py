# SPDX-License-Identifier: MIT
"""SVG writer: every output must be well-formed XML, and every paint attribute
must survive the trip from :class:`~makeyourtree.scene.marks.Paint` to the file."""
from __future__ import annotations

import base64
import xml.etree.ElementTree as ET

import pytest

from makeyourtree.render.svg import SvgBackend, render_svg
from makeyourtree.scene.marks import (Anchor, Baseline, Cap, EllipseMark, GroupMark,
                                  ImageMark, Join, Layer, LinesMark, Paint,
                                  PathMark, PolygonMark, PolylineMark, RectMark,
                                  RectsMark, Scene, TextMark, TextStyle)
from makeyourtree.style.color import Color

from _render_support import SVG_NS, parse_svg

RED = Color(220, 38, 38)
BLUE = Color(37, 99, 235, 128)


def _one_of_every_mark() -> Scene:
    scene = Scene(width=300, height=200, background=Color(255, 255, 255))
    scene.add(RectMark(paint=Paint.filled(RED), x=1, y=2, w=10, h=20, rx=2),
              Layer.UNDERLAY)
    scene.add(RectsMark(paint=Paint(fill=None, stroke=RED, width=0.5),
                        coords=[0, 0, 5, 5, 5, 0, 5, 5],
                        fills=[RED, BLUE]), Layer.TRACKS)
    scene.add(LinesMark(paint=Paint.stroked(RED, 2.0), coords=[0, 0, 10, 10]),
              Layer.BRANCHES)
    scene.add(PolylineMark(paint=Paint.stroked(RED), points=[0, 0, 3, 4, 6, 1]),
              Layer.GRID)
    scene.add(PolygonMark(paint=Paint.filled(BLUE), points=[0, 0, 4, 0, 2, 5]),
              Layer.COLLAPSED)
    scene.add(EllipseMark(paint=Paint.filled(RED), cx=5, cy=5, rx=3, ry=3),
              Layer.DECOR)
    scene.add(EllipseMark(paint=Paint.filled(RED), cx=5, cy=5, rx=3, ry=6),
              Layer.DECOR)
    scene.add(PathMark(paint=Paint.stroked(RED),
                       segments=(("M", 0, 0), ("L", 1, 1), ("Q", 2, 2, 3, 3),
                                 ("C", 4, 4, 5, 5, 6, 6),
                                 ("A", 10, 10, 5, 0, 90, False), ("Z",))),
              Layer.CONNECTIONS)
    scene.add(TextMark(x=3, y=4, text="A & B < C > D \"quoted\"",
                       style=TextStyle(anchor=Anchor.MIDDLE)), Layer.LABELS)
    scene.add(ImageMark(x=0, y=0, w=8, h=8, data=b"\x89PNG-fake",
                        mime="image/png"), Layer.TRACKS)
    scene.add(GroupMark(marks=(RectMark(paint=Paint.filled(RED), w=2, h=2),),
                        dx=5, dy=6, clip=(0, 0, 20, 20)), Layer.TRACKS)
    scene.add(RectMark(paint=Paint.filled(RED), x=0, y=0, w=3, h=3),
              Layer.OVERLAY)
    return scene


def test_every_mark_type_renders_valid_xml():
    root = parse_svg(render_svg(_one_of_every_mark()))
    assert root.tag == SVG_NS + "svg"
    assert root.get("viewBox") == "0 0 300 200"


def test_layers_become_groups_in_painting_order():
    root = parse_svg(render_svg(_one_of_every_mark()))
    classes = [g.get("class") for g in root.iter(SVG_NS + "g")
               if (g.get("class") or "").startswith("makeyourtree-")]
    order = [layer.value for layer in Layer.order()]
    seen = [c.split("makeyourtree-", 1)[1] for c in classes]
    assert seen == [name for name in order if f"makeyourtree-{name}" in classes]
    assert "makeyourtree-overlay" not in classes


def test_overlay_is_excluded_unless_requested():
    without = render_svg(_one_of_every_mark())
    with_overlay = render_svg(_one_of_every_mark(), include_overlay=True)
    assert 'class="makeyourtree-overlay"' not in without
    assert 'class="makeyourtree-overlay"' in with_overlay
    parse_svg(with_overlay)


def test_background_rect_carries_theme_colour():
    scene = Scene(width=10, height=10, background=Color(1, 2, 3))
    root = parse_svg(render_svg(scene))
    rect = root.find(SVG_NS + "rect")
    assert rect is not None
    assert rect.get("fill") == "#010203"
    assert rect.get("width") == "10"


def test_transparent_background_emits_no_rect():
    scene = Scene(width=10, height=10, background=Color(0, 0, 0, 0))
    root = parse_svg(render_svg(scene))
    assert root.find(SVG_NS + "rect") is None


def test_stroke_attributes_round_trip():
    paint = Paint(fill=None, stroke=Color(10, 20, 30, 128), width=2.5,
                  dash=(4.0, 2.0), cap=Cap.ROUND, join=Join.BEVEL, opacity=0.5)
    scene = Scene(width=10, height=10)
    scene.add(LinesMark(paint=paint, coords=[0, 0, 1, 1]), Layer.BRANCHES)
    root = parse_svg(render_svg(scene))
    path = next(root.iter(SVG_NS + "path"))
    assert path.get("stroke") == "#0a141e"
    assert path.get("stroke-width") == "2.5"
    assert path.get("stroke-dasharray") == "4,2"
    assert path.get("stroke-linecap") == "round"
    assert path.get("stroke-linejoin") == "bevel"
    # 128/255 * 0.5 == 0.251
    assert float(path.get("stroke-opacity")) == pytest.approx(0.251, abs=1e-3)
    assert path.get("fill") == "none"


def test_default_cap_and_join_are_omitted():
    scene = Scene(width=10, height=10)
    scene.add(LinesMark(paint=Paint.stroked(RED), coords=[0, 0, 1, 1]),
              Layer.BRANCHES)
    path = next(parse_svg(render_svg(scene)).iter(SVG_NS + "path"))
    assert path.get("stroke-linecap") is None
    assert path.get("stroke-linejoin") is None


def test_fill_alpha_becomes_fill_opacity():
    scene = Scene(width=10, height=10)
    scene.add(RectMark(paint=Paint.filled(Color(0, 0, 0, 51)), w=4, h=4),
              Layer.TRACKS)
    rect = [r for r in parse_svg(render_svg(scene)).iter(SVG_NS + "rect")][0]
    assert float(rect.get("fill-opacity")) == pytest.approx(0.2, abs=1e-3)


def test_rects_batch_is_one_group_sharing_the_stroke():
    coords = []
    fills = []
    for i in range(20):
        coords.extend((i * 3.0, 0.0, 2.0, 6.0))
        fills.append(Color(i * 10 % 256, 0, 0))
    scene = Scene(width=100, height=20)
    scene.add(RectsMark(paint=Paint(fill=None, stroke=Color(0, 0, 0), width=0.4),
                        coords=coords, fills=fills), Layer.TRACKS)
    root = parse_svg(render_svg(scene))
    groups = [g for g in root.iter(SVG_NS + "g") if g.get("stroke")]
    assert len(groups) == 1
    rects = list(groups[0])
    assert len(rects) == 20
    assert groups[0].get("stroke-width") == "0.4"
    assert all(r.get("stroke") is None for r in rects)
    assert rects[3].get("fill") == "#1e0000"


def test_rects_batch_without_fills_puts_fill_on_the_group():
    scene = Scene(width=10, height=10)
    scene.add(RectsMark(paint=Paint.filled(RED), coords=[0, 0, 2, 2, 4, 0, 2, 2]),
              Layer.TRACKS)
    group = [g for g in parse_svg(render_svg(scene)).iter(SVG_NS + "g")
             if g.get("fill")][0]
    assert group.get("fill") == "#dc2626"


def test_negative_rect_extent_is_normalised():
    scene = Scene(width=20, height=20)
    scene.add(RectMark(paint=Paint.filled(RED), x=10, y=10, w=-4, h=-6),
              Layer.TRACKS)
    rect = [r for r in parse_svg(render_svg(scene)).iter(SVG_NS + "rect")][0]
    assert (rect.get("x"), rect.get("y")) == ("6", "4")
    assert (rect.get("width"), rect.get("height")) == ("4", "6")


def test_text_anchor_baseline_rotation_and_escaping():
    scene = Scene(width=50, height=50)
    scene.add(TextMark(x=10, y=20, text="a<b>&\"c\"", rotation=-45.0,
                       style=TextStyle(anchor=Anchor.END,
                                       baseline=Baseline.HANGING,
                                       italic=True, weight=700,
                                       letter_spacing=0.5,
                                       color=Color(0, 0, 0, 204))),
              Layer.LABELS)
    raw = render_svg(scene)
    node = next(parse_svg(raw).iter(SVG_NS + "text"))
    assert node.get("text-anchor") == "end"
    assert node.get("dominant-baseline") == "hanging"
    assert node.get("transform") == "rotate(-45 10 20)"
    assert node.get("font-style") == "italic"
    assert node.get("font-weight") == "700"
    assert node.get("letter-spacing") == "0.5"
    assert float(node.get("fill-opacity")) == pytest.approx(0.8, abs=1e-2)
    assert node.text == 'a<b>&"c"'
    assert "&lt;b&gt;" in raw


def test_start_anchor_and_alphabetic_baseline_are_left_implicit():
    scene = Scene(width=50, height=50)
    scene.add(TextMark(x=1, y=2, text="plain",
                       style=TextStyle(anchor=Anchor.START,
                                       baseline=Baseline.ALPHABETIC)),
              Layer.LABELS)
    node = next(parse_svg(render_svg(scene)).iter(SVG_NS + "text"))
    assert node.get("text-anchor") is None
    assert node.get("dominant-baseline") is None


def test_image_becomes_a_base64_data_uri():
    payload = b"\x89PNG\r\n\x1a\n-not-a-real-png"
    scene = Scene(width=20, height=20)
    scene.add(ImageMark(x=1, y=2, w=8, h=9, data=payload, mime="image/png"),
              Layer.TRACKS)
    node = next(parse_svg(render_svg(scene)).iter(SVG_NS + "image"))
    href = node.get("href")
    assert href.startswith("data:image/png;base64,")
    assert base64.b64decode(href.split(",", 1)[1]) == payload
    assert node.get("width") == "8"


def test_group_translation_and_clip_reach_the_defs():
    scene = Scene(width=40, height=40)
    scene.add(GroupMark(marks=(RectMark(paint=Paint.filled(RED), w=3, h=3),),
                        dx=4, dy=5, clip=(0, 0, 10, 12)), Layer.TRACKS)
    root = parse_svg(render_svg(scene))
    clips = list(root.iter(SVG_NS + "clipPath"))
    assert len(clips) == 1
    clip_rect = clips[0][0]
    assert (clip_rect.get("width"), clip_rect.get("height")) == ("10", "12")
    inner = [g for g in root.iter(SVG_NS + "g") if g.get("transform")]
    assert inner[0].get("transform") == "translate(4 5)"
    assert inner[0].get("clip-path") == "url(#makeyourtree-clip1)"
    assert len(list(inner[0])) == 1


def test_numbers_are_trimmed_to_the_requested_precision():
    scene = Scene(width=10, height=10)
    scene.add(LinesMark(paint=Paint.stroked(RED),
                        coords=[1.0, 2.500000, 3.123456, 4.0]), Layer.BRANCHES)
    d = next(parse_svg(render_svg(scene, precision=2)).iter(SVG_NS + "path")).get("d")
    assert d == "M1 2.5L3.12 4"


def test_title_and_description_are_emitted_and_escaped():
    scene = Scene(width=10, height=10)
    root = parse_svg(render_svg(scene, title="A & B", description="x<y"))
    assert root.find(SVG_NS + "title").text == "A & B"
    assert root.find(SVG_NS + "desc").text == "x<y"


def test_backend_end_returns_utf8_bytes():
    backend = SvgBackend()
    backend.begin(Scene(width=1, height=1))
    backend.draw_text(TextMark(x=0, y=0, text="é中"))
    data = backend.end()
    assert isinstance(data, bytes)
    assert "é中" in data.decode("utf-8")
    ET.fromstring(data.decode("utf-8"))


def test_empty_marks_are_skipped_entirely():
    scene = Scene(width=10, height=10)
    scene.add(LinesMark(paint=Paint.stroked(RED), coords=[]), Layer.BRANCHES)
    scene.add(TextMark(x=0, y=0, text=""), Layer.LABELS)
    scene.add(EllipseMark(paint=Paint.filled(RED), rx=0, ry=0), Layer.DECOR)
    scene.add(ImageMark(x=0, y=0, w=0, h=0, data=b""), Layer.TRACKS)
    root = parse_svg(render_svg(scene))
    assert list(root.iter(SVG_NS + "path")) == []
    assert list(root.iter(SVG_NS + "text")) == []
    assert list(root.iter(SVG_NS + "circle")) == []
    assert list(root.iter(SVG_NS + "image")) == []

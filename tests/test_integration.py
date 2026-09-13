# SPDX-License-Identifier: MIT
"""Journeys that cross unit boundaries.

Nine units built MakeYourTree in parallel against the frozen contracts in
``docs/SPEC.md`` section 2.  Each one's own suite proves its half of a seam;
none of them can prove the seam itself.  These tests walk the whole path a user
actually takes -- parse a file, edit the tree, attach annotations, lay it out,
draw it, save it, reopen it -- and assert the properties that only hold if
every unit agrees with its neighbours.

Three classes of defect live here and nowhere else:

*Return values dropped at a boundary.*  Everything in :mod:`makeyourtree.ops`
BUILDS a reversible command and returns it without touching the tree.  A caller
that ignores the return value gets a silent no-op, and every test that only
checks "a tree came out" passes.

*Two units computing the same quantity.*  When the compositor rounds its own
scale-bar numbers instead of asking :mod:`makeyourtree.layout.scalebar`, the two
answers drift and the figure disagrees with itself.

*A request the layout could not honour.*  ``RADIAL`` lays its along axis out
topologically whatever ``branch_mode`` asked for, so a consumer trusting the
request rather than the result prints a distance scale on a drawing that has no
distances.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from makeyourtree.annot import load_annotation
from makeyourtree.core.diagnostics import DiagnosticSink
from makeyourtree.core.traversal import iter_leaves
from makeyourtree.doc import Document, load_project, save_project
from makeyourtree.io import load_tree, save_tree
from makeyourtree.layout import BranchMode, LayoutMode, LayoutParams, compute_layout
from makeyourtree.ops import collapse, ladderize, midpoint_root
from makeyourtree.render import render_svg
from makeyourtree.scene import compose
from makeyourtree.scene.marks import GroupMark, Layer, TextMark

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "makeyourtree"
EXAMPLES = ROOT / "examples"
SVG_NS = "{http://www.w3.org/2000/svg}"

NEWICK = (
    "(((Alpha:0.10,Bravo:0.20)ab:0.30,(Charlie:0.15,Delta:0.25)cd:0.20)abcd:0.10,"
    "(Echo:0.40,Foxtrot:0.35)ef:0.30,Golf:0.60);"
)
TIPS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf"]

STRIP_CANN = "\n".join([
    "#makeyourtree-annotation 1",
    "",
    "[track]",
    "type = color-strip",
    "title = Clade",
    "",
    "[columns]",
    "names = group",
    "",
    "[colors]",
    "alpha = #E66100",
    "beta = #5D3A9B",
    "",
    "[data]",
    "Alpha\talpha",
    "Bravo\talpha",
    "Charlie\tbeta",
    "Delta\tbeta",
    "Echo\talpha",
    "Foxtrot\t-",
    "Golf\tbeta",
    "",
])

BARS_CANN = "\n".join([
    "#makeyourtree-annotation 1",
    "",
    "[track]",
    "type = bar-chart",
    "title = Abundance",
    "",
    "[options]",
    "thickness = 70",
    "",
    "[columns]",
    "names = count",
    "",
    "[data]",
    "Alpha\t12",
    "Bravo\t7",
    "Charlie\t19",
    "Delta\t3",
    "Echo\t22",
    "Foxtrot\t14",
    "Golf\t9",
    "",
])


# ------------------------------------------------------------------ helpers


def _svg_points(root, attr: str) -> float:
    """The SVG root's width/height in points.

    They carry an explicit ``pt`` because a unitless SVG length is a CSS pixel
    (1/96 in) while a scene unit is a point (1/72 in); without the unit the same
    figure imported 25% smaller as SVG than as PDF. See
    ``makeyourtree.render.sizing``.
    """
    return float(root.get(attr).removesuffix("pt"))


def flatten(marks):
    """Every leaf mark, descending through the translation groups.

    The compositor wraps each layer in one :class:`GroupMark` when content
    overhangs the page origin, rather than rewriting every coordinate.  A test
    counting marks has to see through that.
    """
    for mark in marks:
        if isinstance(mark, GroupMark):
            yield from flatten(mark.marks)
        else:
            yield mark


def layer_marks(scene, layer):
    return list(flatten(scene.layers.get(layer, ())))


def label_texts(scene, layer=Layer.LABELS):
    return {m.text for m in layer_marks(scene, layer) if isinstance(m, TextMark)}


def build_document(mode=LayoutMode.RECTANGULAR, **params):
    """The shared journey: parse, ladderize, midpoint-root, collapse, annotate."""
    sink = DiagnosticSink()
    tree = load_tree(NEWICK, sink=sink)

    ladderize(tree).apply(tree)
    midpoint_root(tree).apply(tree)
    tree.refresh()

    target = tree.by_name("cd")
    assert target is not None, "the clade to collapse survived rerooting"
    collapse(tree, target).apply(tree)
    tree.refresh()

    tracks = [load_annotation(STRIP_CANN, tree, sink=sink),
              load_annotation(BARS_CANN, tree, sink=sink)]
    document = Document(tree=tree, params=LayoutParams(mode=mode, **params),
                        tracks=tracks, title="integration")
    return document, sink


# ------------------------------------------------------- the core is Qt-free


def test_no_module_under_src_imports_qt():
    """SPEC section 1: nothing under ``src/makeyourtree/`` may import PySide6 or PyQt.

    ``tests/test_licensing.py`` greps for the import statement at the start of a
    line.  This one parses every module instead, so an import hidden inside a
    function body, a lazy import in a property, or an
    ``importlib.import_module("PySide6.QtCore")`` is caught too.
    """
    banned = re.compile(r"^(PySide\d|PyQt\d|shiboken\d?)$")
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if banned.match(alias.name.split(".")[0]):
                        offenders.append(f"{rel}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                head = (node.module or "").split(".")[0]
                if banned.match(head):
                    offenders.append(f"{rel}:{node.lineno} from {node.module}")
            elif isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in ("import_module", "__import__") and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if banned.match(arg.value.split(".")[0]):
                            offenders.append(
                                f"{rel}:{node.lineno} {name}({arg.value!r})")
    assert not offenders, "the MIT core must stay toolkit-free: " + "; ".join(offenders)


def test_importing_every_core_module_never_pulls_in_qt():
    """The static check above cannot see a transitive import; this one can.

    Run in a child interpreter because the assertion is about the *whole
    process*: ``sys.modules`` is global, so any studio test that ran earlier in
    this session would have imported PySide6 already and the check would fail
    for a reason that has nothing to do with the core.  A clean subprocess is
    also the stronger claim -- it proves the core imports Qt-free from a cold
    interpreter, which is what an embedder gets.
    """
    import subprocess
    import sys

    probe = (
        "import importlib, pkgutil, sys, makeyourtree\n"
        "for info in pkgutil.walk_packages(makeyourtree.__path__, 'makeyourtree.'):\n"
        "    importlib.import_module(info.name)\n"
        "banned = {'PySide6', 'PySide2', 'PyQt5', 'PyQt6', 'shiboken6'}\n"
        "found = sorted(banned & {n.split('.')[0] for n in sys.modules})\n"
        "sys.stdout.write(','.join(found))\n"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run([sys.executable, "-c", probe], env=env,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", (
        "the MIT core must stay toolkit-free, but importing it pulled in: "
        + result.stdout)


def test_every_subpackage_exports_what_it_declares():
    """``__all__`` is the published API.

    A name in it that does not resolve is a rename applied on one side of a
    unit boundary and not the other -- which nothing else notices until an
    unrelated import fails.
    """
    import importlib
    import pkgutil

    import makeyourtree

    missing: list[str] = []
    names = ["makeyourtree"] + [i.name for i in
                            pkgutil.walk_packages(makeyourtree.__path__, "makeyourtree.")]
    for name in names:
        module = importlib.import_module(name)
        for exported in getattr(module, "__all__", ()):
            if not hasattr(module, exported):
                missing.append(f"{name}.{exported}")
    assert not missing, "declared but absent: " + ", ".join(missing)


# ------------------------------------------------------------ the full journey


@pytest.mark.parametrize("mode", list(LayoutMode))
def test_the_whole_journey_renders_in_every_layout_mode(mode):
    """Parse, edit, annotate, compose, render -- in all five modes.

    The SVG has to carry all three contributors: geometry from the tree, marks
    from the two tracks, and the legend the tracks asked for.  A track that
    silently drew nothing, or a legend that never made it onto the page, is the
    failure this catches.
    """
    document, _ = build_document(mode)
    scene = compose(document)
    svg = render_svg(scene)

    root = ET.fromstring(svg)
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("width").endswith("pt") and root.get("height").endswith("pt")
    assert _svg_points(root, "width") > 0 and _svg_points(root, "height") > 0

    assert layer_marks(scene, Layer.BRANCHES), "no branch geometry"
    assert layer_marks(scene, Layer.COLLAPSED), "the collapsed clade drew no glyph"
    assert layer_marks(scene, Layer.TRACKS), "neither track drew anything"
    assert layer_marks(scene, Layer.LEGEND), "the legend is missing"

    texts = label_texts(scene)
    assert "Alpha" in texts and "Golf" in texts

    legend_text = label_texts(scene, Layer.LEGEND)
    assert {"alpha", "beta"} <= legend_text, (
        f"the colour strip's categories are not in the legend: {legend_text}")
    assert "Clade" in legend_text or "Abundance" in legend_text

    assert "#e66100" in svg.lower(), (
        "a colour pinned in the table's [colors] section never reached the SVG")


@pytest.mark.parametrize("mode", list(LayoutMode))
def test_a_saved_project_reopens_and_redraws_identically(mode, tmp_path):
    """Save, reload, recompose -- byte for byte.

    This is the strongest single statement about the document layer: every
    quantity the drawing depends on (topology, node ids, the collapsed set,
    layout params, theme, and both tracks' bound rows and options) survived the
    round trip through the ZIP container and came back in the same order.  One
    dropped field moves one coordinate and the two strings differ.
    """
    document, _ = build_document(mode)
    first = render_svg(compose(document))

    path = tmp_path / "project.mytree"
    save_project(document, path)
    reopened = load_project(path)

    assert [t.type_id for t in reopened.tracks] == [t.type_id for t in document.tracks]
    assert ([n.name for n in reopened.tree.collapsed_nodes()]
            == [n.name for n in document.tree.collapsed_nodes()])

    second = render_svg(compose(reopened))
    assert second == first, "the reopened project draws a different figure"


def test_the_flat_project_variant_round_trips_too(tmp_path):
    document, _ = build_document()
    first = render_svg(compose(document))
    path = tmp_path / "project.mytree.json"
    save_project(document, path, flat=True)
    assert render_svg(compose(load_project(path))) == first


# -------------------------------------------- operations reach the layout


def test_ladderize_and_midpoint_root_are_not_silent_no_ops():
    """Every ``ops`` entry point returns a command; the caller must apply it.

    Asserted here rather than only in the ops suite because the interesting
    failure is at the boundary: a caller that drops the return value still
    produces a tree, still lays it out and still renders, so nothing downstream
    complains.  ``makeyourtree.cli`` had exactly this bug.
    """
    tree = load_tree(NEWICK)
    before = tree.to_newick()

    command = ladderize(tree)
    assert tree.to_newick() == before, "ops must not mutate before apply()"
    command.apply(tree)
    tree.refresh()
    assert tree.to_newick() != before, "ladderize did nothing when applied"

    total_before = sum(n.branch_length or 0.0 for n in tree.nodes)
    midpoint_root(tree).apply(tree)
    tree.refresh()
    depths = sorted(leaf.depth_len for leaf in iter_leaves(tree.root))
    assert depths[-1] == pytest.approx(depths[-2]), (
        "a midpoint root leaves the two deepest tips equidistant")
    assert sum(n.branch_length or 0.0 for n in tree.nodes) == pytest.approx(
        total_before), "rerooting moves length between edges, it never creates it"


def test_collapsing_a_clade_removes_its_tips_and_draws_one_glyph():
    """Collapse is a layout-visible edit, not a style flag.

    The hidden tips must stop consuming rows, or the drawing keeps a gap where
    the clade used to be and the tracks beside it line up with nothing.
    """
    document, _ = build_document()
    expanded = load_tree(NEWICK)
    expanded.refresh()

    all_tips = compute_layout(expanded, LayoutParams()).tips
    collapsed_tips = compute_layout(document.tree, document.params).tips
    assert len(collapsed_tips) < len(all_tips)

    scene = compose(document)
    labels = label_texts(scene)
    assert "Charlie" not in labels and "Delta" not in labels, (
        "tips inside a collapsed clade must not be labelled")
    assert len(layer_marks(scene, Layer.COLLAPSED)) == 1


# ------------------------------------ the layout and the compositor agree


@pytest.mark.parametrize("mode", [LayoutMode.RECTANGULAR, LayoutMode.SLANTED,
                                  LayoutMode.CIRCULAR])
def test_the_scale_bar_matches_the_layout_units_it_claims(mode):
    """The bar on the page must be the bar :mod:`makeyourtree.layout.scalebar` sized.

    The compositor used to round its own nice numbers off the tree body's
    bounding box.  In a fan that box is the DIAMETER, so the circular figure
    claimed a unit five times the one the linear figure claimed for the same
    tree -- and the axis ladder beside it agreed with neither.
    """
    from makeyourtree.layout.scalebar import scale_bar

    document, _ = build_document(mode)
    frame = compute_layout(document.tree, document.params)
    expected = scale_bar(frame, document.params, document.theme)
    assert expected is not None

    scene = compose(document)
    units, pixels = scene.metadata["scalebar"]
    assert units == pytest.approx(expected.units)
    assert pixels == pytest.approx(expected.pixels)
    assert pixels == pytest.approx(units * frame.scale), (
        "the drawn length must be the claimed length times the frame's scale")


def test_a_radial_phylogram_refuses_to_print_a_distance_scale():
    """``RADIAL`` ignores ``branch_mode`` -- so nothing may claim it did not.

    Its contract is that the tips form a ring, which it delivers by laying the
    along axis out topologically and leaving ``frame.scale`` at the cladogram
    sentinel of 1.0.  Building a scale bar from ``branch_mode`` alone then
    printed "500" beside a tree whose deepest tip sits at 0.7.  The layout
    publishes the rule it actually realised; every consumer reads that instead.
    """
    from makeyourtree.layout.along import ALONG_LENGTH, along_is_length, along_rule

    params = LayoutParams(mode=LayoutMode.RADIAL, branch_mode=BranchMode.PHYLOGRAM)
    document, _ = build_document(LayoutMode.RADIAL,
                                 branch_mode=BranchMode.PHYLOGRAM)
    frame = compute_layout(document.tree, params)

    assert params.branch_mode.uses_lengths, "the user did ask for a phylogram"
    assert along_rule(frame, params) != ALONG_LENGTH
    assert not along_is_length(frame, params)

    scene = compose(document)
    assert "scalebar" not in scene.metadata, (
        "a radial fan has no distance axis, so it must not print a length")


def test_polar_axis_rings_stay_inside_the_drawing():
    """Rings are radii, and a fan's bounding box is twice its radius.

    Deriving the tick ladder from ``body_bounds`` put half the rings outside the
    figure entirely, and measuring from the centre rather than from
    ``metadata["base_radius"]`` started the ladder inside the central hole.
    """
    from makeyourtree.layout.scalebar import axis_ticks

    params = LayoutParams(mode=LayoutMode.CIRCULAR)
    document, _ = build_document(LayoutMode.CIRCULAR)
    document.theme = dataclasses.replace(document.theme, axis_show=True)
    frame = compute_layout(document.tree, params)

    ticks = axis_ticks(frame, params)
    assert ticks, "a circular phylogram has a distance axis"
    inner = frame.metadata["inner_radius"]
    for _value, radius, _label in ticks:
        assert inner - 1e-6 <= radius <= frame.max_radius + 1e-6, (
            f"ring at r={radius:g} is outside [{inner:g}, {frame.max_radius:g}]")

    scene = compose(document)
    drawn = [seg[3] for mark in layer_marks(scene, Layer.GRID)
             for seg in getattr(mark, "segments", ()) if seg[0] == "A"]
    assert drawn, "axis_show was on, so rings should have been drawn"
    assert max(drawn) <= frame.max_radius + 1e-6


@pytest.mark.parametrize("mode", list(LayoutMode))
def test_every_layout_publishes_the_along_rule_it_realised(mode):
    """The cross-unit vocabulary the scale bar, the axis ladder and the
    collapsed-clade glyph all read.  A layout that does not publish it leaves
    three consumers guessing from ``branch_mode``, which records a request
    rather than a result."""
    from makeyourtree.layout.along import (ALONG_ALIGNED, ALONG_LENGTH, ALONG_LEVEL,
                                       ALONG_METADATA_KEY)

    tree = load_tree(NEWICK)
    tree.refresh()
    for branch_mode in BranchMode:
        frame = compute_layout(tree, LayoutParams(mode=mode,
                                                  branch_mode=branch_mode))
        recorded = frame.metadata.get(ALONG_METADATA_KEY)
        assert recorded in (ALONG_LENGTH, ALONG_LEVEL, ALONG_ALIGNED), (
            f"{mode.value}/{branch_mode.value} published {recorded!r}")


def test_an_unrooted_layout_says_its_track_positions_are_indicative():
    """An unrooted drawing has no tip order, so its band space is a fiction.

    The layout is honest about it in ``frame.metadata``; the compositor draws
    the tracks anyway, which is better than dropping them, but the user has no
    way to know unless someone passes the caveat on.
    """
    document, _ = build_document(LayoutMode.UNROOTED)
    sink = DiagnosticSink()
    compose(document, sink=sink)
    codes = {d.code for d in sink}
    assert "compose.approximate-band-space" in codes, (
        f"tracks were placed in an approximate band space silently: {codes}")


@pytest.mark.parametrize("mode", list(LayoutMode))
def test_every_layout_reports_the_lengths_it_flattened(mode):
    """Clamping a negative length changes what the figure claims.

    Neighbour-joining and least-squares fitting both produce negative lengths;
    drawing them as zero is the only sensible picture, but a reader who is not
    told will measure the figure and get a number the data never contained.
    """
    tree = load_tree("((Alpha:-0.4,Beta:0.2):0.1,(Gamma:0.3,Delta:-0.1):0.2);")
    document = Document(tree=tree, params=LayoutParams(mode=mode))
    sink = DiagnosticSink()
    compose(document, sink=sink)
    codes = {d.code for d in sink}
    assert "layout.negative-lengths-clamped" in codes, codes
    message = next(d.message for d in sink
                   if d.code == "layout.negative-lengths-clamped")
    assert message.startswith("2 negative branch length(s)")


def test_a_tree_without_negative_lengths_draws_without_that_warning():
    document, _ = build_document()
    sink = DiagnosticSink()
    compose(document, sink=sink)
    assert "layout.negative-lengths-clamped" not in {d.code for d in sink}


@pytest.mark.parametrize("mode", list(LayoutMode))
def test_a_node_marker_is_drawn_and_survives_a_save(mode, tmp_path):
    """``NodeStyle.marker_shape`` names :data:`makeyourtree.tracks.shapes.SHAPES`.

    The frozen contract names both ends of this seam, but nothing joined them:
    the key could be set, it round-tripped through the project file, and no
    mark was ever drawn.  Because the shapes registry works in band space, one
    call serves all five modes.
    """
    from makeyourtree.scene.marks import PathMark
    from makeyourtree.style.color import Color

    tree = load_tree(NEWICK)
    tree.refresh()
    marked = [n for n in tree.nodes if n.name in ("Alpha", "Golf", "ab")]
    assert len(marked) == 3
    for node, shape in zip(marked, ("circle", "star", "triangle")):
        node.style = {"marker_shape": shape, "marker_color": Color(220, 40, 40),
                      "marker_size": 9.0}

    document = Document(tree=tree, params=LayoutParams(mode=mode))
    scene = compose(document)
    markers = [m for m in layer_marks(scene, Layer.DECOR)
               if isinstance(m, PathMark) and m.tag in {n.id for n in marked}]
    assert len(markers) == 3, f"{mode.value}: expected 3 node markers"

    path = tmp_path / "marked.mytree"
    save_project(document, path)
    assert render_svg(compose(load_project(path))) == render_svg(scene)


@pytest.mark.parametrize("mode", list(LayoutMode))
def test_a_clade_fill_and_clade_label_both_reach_the_page(mode):
    """The other two ``NodeStyle`` keys naming a whole clade.

    ``clade_fill`` was wired up; ``clade_label`` was the same unjoined seam as
    ``marker_shape`` -- a key in the frozen contract that round-tripped through
    the project file and drew nothing.  It goes through ``projector.text``, so
    a fan rotates it onto its own radius instead of laying it across the rings.
    """
    from makeyourtree.style.color import Color

    tree = load_tree(NEWICK)
    tree.refresh()
    clade = tree.by_name("ab")
    clade.style = {"clade_fill": Color(255, 200, 200), "clade_label": "Group A"}

    scene = compose(Document(tree=tree, params=LayoutParams(mode=mode)))
    assert layer_marks(scene, Layer.UNDERLAY), "clade_fill painted nothing"
    assert "Group A" in label_texts(scene), "clade_label was never drawn"
    assert "Group A" in render_svg(scene)


def test_a_reversed_quad_still_draws():
    """``QuadBatch`` is shared by every cell-shaped track, and a bar running back
    from its baseline to a negative value names its far corner first.  A
    negative width is an error in SVG, so the quad vanished -- in the linear
    projection only, which is why a suite run against one projector missed it.
    """
    from makeyourtree.layout.projector import LinearProjector
    from makeyourtree.scene.marks import Scene
    from makeyourtree.style.color import Color
    from makeyourtree.tracks.shapes import QuadBatch

    scene = Scene()
    batch = QuadBatch(LinearProjector(base_x=100.0, top_y=0.0,
                                      row_height=10.0, n_rows=4))
    batch.add(0.0, 1.0, 40.0, 10.0, Color(200, 0, 0))
    batch.add(1.0, 2.0, 10.0, 40.0, Color(0, 0, 200))
    batch.flush(scene.sink(Layer.TRACKS))

    coords = layer_marks(scene, Layer.TRACKS)[0].coords
    widths = coords[2::4]
    assert all(w > 0 for w in widths), f"a quad collapsed to zero area: {widths}"
    assert widths[0] == pytest.approx(widths[1])


def test_the_two_legend_item_records_stay_structurally_identical():
    """``style.scales`` cannot import ``tracks.base``.

    ``tracks.base`` imports ``style``, so the dependency runs one way only and
    the reverse import is a cycle.  ``scales`` therefore declares its own
    ``LegendItem`` with the same fields in the same order, and a track passes
    those objects straight into a :class:`Legend`.  Nothing enforces the match
    but this test -- rename a field on either side and the seam breaks silently.
    """
    from makeyourtree.style.scales import ContinuousScale
    from makeyourtree.style.scales import LegendItem as ScaleItem
    from makeyourtree.tracks.base import Legend
    from makeyourtree.tracks.base import LegendItem as TrackItem

    def shape(cls):
        return [(f.name, f.type) for f in dataclasses.fields(cls)]

    assert shape(ScaleItem) == shape(TrackItem)

    items = ContinuousScale(0.0, 10.0, palette="viridis").legend_items()
    rebuilt = [TrackItem(i.label, i.color, i.shape, i.gradient, i.value_range)
               for i in items]
    assert Legend(title="t", items=rebuilt, kind="continuous")


# ---------------------------------------------------------- formats and files


@pytest.mark.parametrize("fmt,suffix", [("newick", ".nwk"), ("nexus", ".nex"),
                                        ("phyloxml", ".xml")])
def test_a_tree_survives_a_trip_through_every_writer(fmt, suffix, tmp_path):
    """Topology, names, lengths and support have to come back from all three.

    ``support=True`` is passed to each: ``write_tree`` forwards its keywords
    verbatim, so a writer missing one of the shared option names raises
    ``TypeError`` for a call that is valid against the other two.
    """
    original = load_tree(NEWICK)
    original.refresh()
    path = tmp_path / f"tree{suffix}"
    save_tree(original, path, format=fmt, support=True)

    again = load_tree(path)
    again.refresh()
    assert again.n_leaves == original.n_leaves
    assert sorted(n.name for n in iter_leaves(again.root)) == sorted(TIPS)
    assert again.max_root_to_tip == pytest.approx(original.max_root_to_tip)


def test_an_annotation_bound_to_one_format_binds_to_the_others(tmp_path):
    """Tracks match on node NAME, so a table written against one file must
    attach to the same tree read back from any format.  Quoting differences
    between the writers are what breaks this."""
    original = load_tree(NEWICK)
    original.refresh()
    for fmt, suffix in (("newick", ".nwk"), ("nexus", ".nex"), ("phyloxml", ".xml")):
        path = tmp_path / f"t{suffix}"
        save_tree(original, path, format=fmt)
        tree = load_tree(path)
        tree.refresh()
        track = load_annotation(STRIP_CANN, tree)
        assert not track.data.unmatched, (
            f"{fmt}: keys matched no node: {track.data.unmatched}")
        assert len(track.data.rows) == len(TIPS)


# ------------------------------------------------------------------ examples


@pytest.mark.skipif(not EXAMPLES.exists(), reason="examples/ not present")
@pytest.mark.parametrize("tree_name,track_names", [
    ("primates.nwk", ["primates_region.mytrack", "primates_bodymass.mytrack"]),
    ("bacteria.nwk", ["bacteria_resistance.mytrack", "bacteria_expression.mytrack"]),
    ("domains.nwk", ["domains_labels.mytrack"]),
    ("virus.nex", ["virus_lineage.mytrack", "virus_titre.mytrack"]),
    ("virus.xml", ["virus_lineage.mytrack", "virus_titre.mytrack"]),
])
def test_the_shipped_examples_load_and_render(tree_name, track_names):
    """The examples are the documented starting point, so a broken one is a
    broken first impression.  Every key in every shipped table must match a tip.
    """
    sink = DiagnosticSink()
    tree = load_tree(EXAMPLES / tree_name, sink=sink)
    tree.refresh()

    tracks = []
    for name in track_names:
        track = load_annotation(EXAMPLES / name, tree, sink=sink)
        assert not track.data.unmatched, (
            f"{name} has keys matching no tip in {tree_name}: "
            f"{track.data.unmatched}")
        tracks.append(track)

    document = Document(tree=tree, tracks=tracks)
    root = ET.fromstring(render_svg(compose(document)))
    assert root.get("width").endswith("pt")
    assert _svg_points(root, "width") > 0


@pytest.mark.skipif(not EXAMPLES.exists(), reason="examples/ not present")
def test_the_cli_runs_info_convert_and_render_over_an_example(tmp_path, capsys):
    """The three subcommands, on a real shipped file, checked by their output
    rather than by their exit code alone."""
    import json

    from makeyourtree.cli import main

    source = EXAMPLES / "primates.nwk"

    assert main(["info", str(source), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["leaves"] == 16 and payload["format"] == "newick"

    converted = tmp_path / "primates.xml"
    assert main(["-q", "convert", str(source), str(converted)]) == 0
    assert load_tree(converted).n_leaves == 16

    drawn = tmp_path / "primates.svg"
    assert main(["-q", "render", str(source), str(drawn), "--mode", "circular",
                 "--track", str(EXAMPLES / "primates_region.mytrack")]) == 0
    text = drawn.read_text(encoding="utf-8")
    assert ET.fromstring(text).tag == f"{SVG_NS}svg"
    assert "#117733" in text.lower(), (
        "a colour pinned in the example's [colors] section never reached the SVG")

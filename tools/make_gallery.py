# SPDX-License-Identifier: MIT
"""Render the example gallery: every layout, every track type, every feature.

Run with ``python tools/make_gallery.py``.  Output goes to ``examples/gallery/``
as SVG (vector, produced by the Qt-free core writer), PDF (vector, for the
manual) and PNG (raster, for the README and the web).

Two things about how this runs.

**The real Qt platform, not offscreen.**  The offscreen platform reports zero
font families, so every string would rasterise as tofu and the gallery would be
worthless as a showcase.  ``QT_QPA_PLATFORM`` is therefore cleared before Qt is
imported, exactly as ``smoke_studio.py`` does.

**Everything here is synthetic.**  The trees come from ``examples/*.nwk``, which
``examples/generate.py`` builds from a seeded RNG and invented taxon names, and
the track values below are likewise generated.  Nothing is copied from, derived
from, or checked against another phylogenetics package's bundled data; see
``legal/FIXTURES.md``.
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Must happen before PySide6 is imported: see the module docstring.
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtWidgets import QApplication  # noqa: E402

from makeyourtree.annot.loaders import load_annotation  # noqa: E402
from makeyourtree.core.diagnostics import DiagnosticSink  # noqa: E402
from makeyourtree.doc import Document  # noqa: E402
from makeyourtree.io import load_tree  # noqa: E402
from makeyourtree.layout import (BranchMode, LayoutMode, LayoutParams,  # noqa: E402
                                 UnrootedMethod)
from makeyourtree.ops import collapse, ladderize, midpoint_root  # noqa: E402
from makeyourtree.scene import compose  # noqa: E402
from makeyourtree.style import DARK, LIGHT  # noqa: E402
from makeyourtree.tracks.bars import BarChartTrack  # noqa: E402
from makeyourtree.tracks.binary import BinaryMatrixTrack  # noqa: E402
from makeyourtree.tracks.boxplot import BoxPlotTrack  # noqa: E402
from makeyourtree.tracks.connections import ConnectionsTrack  # noqa: E402
from makeyourtree.tracks.domains import DomainArchitectureTrack  # noqa: E402
from makeyourtree.tracks.gradient import GradientTrack  # noqa: E402
from makeyourtree.tracks.heatmap import HeatmapTrack  # noqa: E402
from makeyourtree.tracks.line import LineChartTrack  # noqa: E402
from makeyourtree.tracks.pie import PieChartTrack  # noqa: E402
from makeyourtree.tracks.ranges import CladeRangeTrack  # noqa: E402
from makeyourtree.tracks.strip import ColorStripTrack  # noqa: E402
from makeyourtree.tracks.symbols import SymbolTrack  # noqa: E402
from makeyourtree.tracks.text import TextLabelTrack  # noqa: E402

from makeyourtree_studio.export.raster import (export_pdf, export_png,  # noqa: E402
                                               export_svg)

OUT = ROOT / "examples" / "gallery"
EX = ROOT / "examples"

#: Colour-vision-safe categorical set (Okabe-Ito derived), used throughout so
#: the gallery reads correctly for deuteranopic and protanopic viewers.
SAFE = ("#117733", "#DDCC77", "#CC6677", "#332288", "#AA4499",
        "#88CCEE", "#44AA99", "#999933")

INDEX: list[tuple[str, str, str]] = []
"""(filename stem, section, caption) for every figure, for the README."""


# ----------------------------------------------------------------- rendering


def figure(stem: str, section: str, caption: str, doc: Document,
           *, png_scale: float = 2.0) -> None:
    """Compose *doc* and write it as SVG, PDF and PNG."""
    sink = DiagnosticSink()
    scene = compose(doc, sink=sink)
    export_svg(scene, OUT / f"{stem}.svg")
    export_pdf(scene, OUT / f"{stem}.pdf")
    export_png(scene, OUT / f"{stem}.png", scale=png_scale)
    INDEX.append((stem, section, caption))
    print(f"  {stem:<34} {scene.width:>6.0f} x {scene.height:<6.0f} {caption}")
    # A figure that quietly lost a track caption still looks finished, which is
    # exactly why the gallery has to say so while it is being regenerated.
    for item in sink.items:
        print(f"      {item.severity.name.lower()}: {item.message}")


def doc_for(tree, *, tracks=(), theme=LIGHT, **params) -> Document:
    return Document(tree=tree, params=LayoutParams(**params),
                    theme=theme, tracks=list(tracks))


# ------------------------------------------------------------------- tracks


def bound(track, tree, rows, columns=None):
    """Bind *rows* (keyed by tip name) and return the track."""
    if columns is None:
        track.bind(tree, rows)
    else:
        track.bind(tree, rows, columns=columns)
    return track


def tips(tree):
    return [n.name for n in tree.nodes if not n.children and n.name]


def strip_track(tree, rng):
    groups = ["Group A", "Group B", "Group C", "Group D"]
    rows = {n: [groups[i % 4]] for i, n in enumerate(tips(tree))}
    colors = {g: SAFE[i] for i, g in enumerate(groups)}
    return bound(ColorStripTrack(title="Host group",
                                 options={"thickness": 18, "border_width": 0.5,
                                          "colors": colors}),
                 tree, rows, ["group"])


def heatmap_track(tree, rng):
    cols = ["0 h", "2 h", "6 h", "12 h", "24 h"]
    rows = {n: [round(rng.gauss(0, 1.4), 2) for _ in cols] for n in tips(tree)}
    return bound(HeatmapTrack(title="Expression (log2)",
                              options={"cell_size": 22.0, "normalize": "global",
                                       "color_min": "#2166AC",
                                       "color_mid": "#F7F7F7",
                                       "color_max": "#B2182B",
                                       "use_mid": True}),
                 tree, rows, cols)


def bar_track(tree, rng, stacked=False):
    if stacked:
        cols = ["core", "shell", "cloud"]
        rows = {n: [rng.uniform(1, 5), rng.uniform(1, 4), rng.uniform(0.5, 3)]
                for n in tips(tree)}
        return bound(BarChartTrack(title="Genome partition (Mb)",
                                   options={"thickness": 100, "stack": True,
                                            "axis": True}),
                     tree, rows, cols)
    rows = {n: [round(rng.uniform(0.3, 160.0), 1)] for n in tips(tree)}
    return bound(BarChartTrack(title="Body mass (kg)",
                               options={"thickness": 95, "color": "#4C7A9C",
                                        "axis": True}),
                 tree, rows, ["mass"])


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20260904)

    primates = load_tree(EX / "primates.nwk")
    bacteria = load_tree(EX / "bacteria.nwk")
    domains_tree = load_tree(EX / "domains.nwk")
    ladderize(primates).apply(primates)

    # ------------------------------------------------------- 1. layout modes
    print("layouts")
    S = "Layouts"
    figure("layout-rectangular-phylogram", S,
           "Rectangular phylogram: branch length along x.",
           doc_for(primates, mode=LayoutMode.RECTANGULAR))
    figure("layout-rectangular-cladogram", S,
           "Rectangular cladogram: depth along x, tips aligned.",
           doc_for(primates, mode=LayoutMode.RECTANGULAR,
                   branch_mode=BranchMode.CLADOGRAM_ALIGNED))
    figure("layout-slanted", S,
           "Slanted (triangular) layout.",
           doc_for(primates, mode=LayoutMode.SLANTED))
    figure("layout-circular", S,
           "Circular fan, 350 degree arc.",
           doc_for(primates, mode=LayoutMode.CIRCULAR))
    figure("layout-circular-full", S,
           "Circular fan closed to a full 360 degree circle.",
           doc_for(primates, mode=LayoutMode.CIRCULAR, arc=360.0,
                   inner_radius=0.18))
    figure("layout-circular-cladogram", S,
           "Circular cladogram: every tip on the outer radius.",
           doc_for(primates, mode=LayoutMode.CIRCULAR,
                   branch_mode=BranchMode.CLADOGRAM_ALIGNED))
    figure("layout-radial", S,
           "Radial: angle from tip order, radius from branch length.",
           doc_for(primates, mode=LayoutMode.RADIAL))
    figure("layout-unrooted-equal-angle", S,
           "Unrooted, Felsenstein equal-angle.",
           doc_for(primates, mode=LayoutMode.UNROOTED,
                   unrooted_method=UnrootedMethod.EQUAL_ANGLE))
    figure("layout-unrooted-equal-daylight", S,
           "Unrooted, equal-daylight: subtrees spread to even the gaps.",
           doc_for(primates, mode=LayoutMode.UNROOTED,
                   unrooted_method=UnrootedMethod.EQUAL_DAYLIGHT))

    # ------------------------------------------------------- 2. track types
    print("tracks")
    S = "Annotation tracks"
    names = tips(primates)

    internal = [n for n in primates.nodes if n.children and n.parent is not None]
    picks = internal[:3]
    ranges = CladeRangeTrack(title="Named clades")
    ranges.data.columns = ["color", "label"]
    ranges.data.rows = {n.id: [SAFE[i], f"Clade {i + 1}"]
                        for i, n in enumerate(picks)}
    figure("track-clade-range", S,
           "Clade range: a shaded, labelled band behind a whole subtree.",
           doc_for(primates, tracks=[ranges]))

    figure("track-color-strip", S,
           "Colour strip: one categorical value per tip.",
           doc_for(primates, tracks=[strip_track(primates, rng)]))

    genes = ["ampC", "blaZ", "mecA", "tetK", "ermB", "vanA"]
    binary = bound(BinaryMatrixTrack(title="Resistance genes",
                                     options={"thickness": 92,
                                              "shape": "square"}),
                   bacteria,
                   {n: [rng.choice([1, 1, 0, 0, -1]) for _ in genes]
                    for n in tips(bacteria)}, genes)
    figure("track-binary-matrix", S,
           "Binary matrix: presence, absence and unknown per gene.",
           doc_for(bacteria, tracks=[binary]))

    grad = bound(GradientTrack(title="Titre (log10)",
                               options={"thickness": 22}),
                 primates, {n: [round(rng.uniform(1.0, 7.5), 2)]
                            for n in names}, ["titre"])
    figure("track-gradient", S,
           "Gradient: a continuous value as a single colour ramp.",
           doc_for(primates, tracks=[grad]))

    figure("track-heatmap", S,
           "Heatmap: a matrix of continuous values, diverging palette.",
           doc_for(bacteria, tracks=[heatmap_track(bacteria, rng)]))

    figure("track-bar-chart", S,
           "Bar chart with a value axis.",
           doc_for(primates, tracks=[bar_track(primates, rng)]))
    figure("track-bar-stacked", S,
           "Stacked bar chart: composition per tip.",
           doc_for(primates, tracks=[bar_track(primates, rng, stacked=True)]))

    box = bound(BoxPlotTrack(title="Replicate spread",
                             options={"thickness": 100, "source": "raw",
                                      "axis": True}),
                primates,
                {n: sorted(round(rng.gauss(5, 2), 2) for _ in range(7))
                 for n in names},
                [f"r{i}" for i in range(7)])
    figure("track-box-plot", S,
           "Box plot: distribution per tip, computed from raw replicates.",
           doc_for(primates, tracks=[box]))

    pie = bound(PieChartTrack(title="Read shares", options={"radius": 9.0, "donut": 0.45}),
                primates,
                {n: [rng.uniform(1, 6), rng.uniform(1, 6), rng.uniform(1, 6)]
                 for n in names},
                ["type I", "type II", "type III"])
    figure("track-pie-chart", S,
           "Pie charts: part-to-whole composition at each tip.",
           doc_for(primates, tracks=[pie]))

    arch = bound(DomainArchitectureTrack(title="Protein architecture",
                                         options={"thickness": 240, "length_column": 0, "show_labels": True,
                                                  "feature_height": 13.0}),
                 primates,
                 {n: [520,
                      f"{20 + 5 * i}|{170 + 5 * i}|rect|#CC6677|Kinase",
                      f"{215 + 4 * i}|{320 + 4 * i}|ellipse|#332288|SH2",
                      f"{360 + 6 * i}|{495}|hexagon|#117733|PDZ"]
                  for i, n in enumerate(names)},
                 ["length", "f1", "f2", "f3"])
    figure("track-domain-architecture", S,
           "Domain architecture: features drawn to scale along each protein.",
           doc_for(primates, tracks=[arch]))

    text = bound(TextLabelTrack(title="Notes",
                                options={"size": 10, "color": "#5A5A66"}),
                 domains_tree,
                 {"Plantae": ["photosynthetic"], "Fungi": ["osmotrophic"],
                  "Metazoa": ["ingestive"], "Firmicutes": ["low GC"],
                  "Proteobacteria": ["gram-negative"],
                  "Euryarchaeota": ["methanogens"],
                  "Crenarchaeota": ["thermophiles"]},
                 ["note"])
    figure("track-text-labels", S,
           "External text labels, independent of the tip names.",
           doc_for(domains_tree, tracks=[text],
                   branch_mode=BranchMode.CLADOGRAM_ALIGNED))

    groups = ["marine", "soil", "host"]
    sym = bound(SymbolTrack(title="Sampling",
                            options={"color_column": 0, "size_column": 1}),
                primates,
                {n: [groups[i % 3], float(rng.randint(1, 40))]
                 for i, n in enumerate(names)},
                ["habitat", "count"])
    figure("track-symbols", S,
           "Symbols sized by value: area encodes magnitude, not radius.",
           doc_for(primates, tracks=[sym]))

    cols = ["t1", "t2", "t3", "t4", "t5", "t6"]
    line = bound(LineChartTrack(title="Time course",
                                options={"thickness": 100, "zero_line": True,
                                         "show_dots": True, "area": True,
                                         "area_opacity": 0.25}),
                 primates,
                 {n: [round(rng.gauss(0, 1.6), 2) for _ in cols] for n in names},
                 cols)
    figure("track-line-chart", S,
           "Line chart: a small multiple series per tip.",
           doc_for(primates, tracks=[line]))

    links = ConnectionsTrack(title="Transfer events",
                             options={"bow": 0.55, "show_labels": True})
    pairs = [(names[0], names[9]), (names[2], names[13]),
             (names[5], names[11]), (names[7], names[15])]
    links.bind(primates, {str(i): [a, b, 1.0 + i, SAFE[i], None, f"event {i + 1}"]
                          for i, (a, b) in enumerate(pairs)})
    figure("track-connections", S,
           "Connections: curved links between arbitrary nodes, drawn under "
           "the branches.",
           doc_for(primates, tracks=[links]))

    # -------------------------------------------------- 3. combined figures
    print("combinations")
    S = "Combined figures"
    stack = [strip_track(bacteria, rng), heatmap_track(bacteria, rng),
             bar_track(bacteria, rng)]
    figure("combined-rectangular", S,
           "Three stacked tracks in a rectangular layout.",
           doc_for(bacteria, tracks=stack, align_tips=True))
    figure("combined-circular", S,
           "The identical tracks in a circular layout. No track code differs "
           "between this figure and the previous one.",
           doc_for(bacteria, tracks=[strip_track(bacteria, rng),
                                     heatmap_track(bacteria, rng),
                                     bar_track(bacteria, rng)],
                   mode=LayoutMode.CIRCULAR, align_tips=True))

    # ---------------------------------------------------------- 4. features
    print("features")
    S = "Features"
    figure("feature-align-tips", S,
           "Tips aligned to a common edge with guide lines.",
           doc_for(primates, tracks=[strip_track(primates, rng)],
                   align_tips=True, guide_lines=True))

    collapsed = load_tree(EX / "primates.nwk")
    ladderize(collapsed).apply(collapsed)
    target = [n for n in collapsed.nodes if n.children and n.parent is not None][0]
    collapse(collapsed, target.id).apply(collapsed)
    figure("feature-collapsed-clade", S,
           "A collapsed clade, drawn as a triangle sized by the subtree.",
           doc_for(collapsed))

    figure("feature-dark-theme", S,
           "The dark theme. The scene carries its own background, so an "
           "export matches the screen.",
           doc_for(primates, tracks=[strip_track(primates, rng)], theme=DARK))

    rerooted = load_tree(EX / "primates.nwk")
    midpoint_root(rerooted).apply(rerooted)
    figure("feature-midpoint-rooted", S,
           "The same tree after midpoint rooting. Patristic distances are "
           "preserved exactly.",
           doc_for(rerooted))

    figure("feature-large-tree", S,
           "A 24-tip tree with a full annotation stack, circular.",
           doc_for(bacteria,
                   tracks=[strip_track(bacteria, rng),
                           heatmap_track(bacteria, rng)],
                   mode=LayoutMode.CIRCULAR, arc=340.0, align_tips=True))

    # ------------------------------------------------- 5. everything at once
    print("showcase")
    S = "Everything at once"
    names_b = tips(bacteria)
    rngs = random.Random(4242)

    def sym_track(tree):
        groups = ["marine", "soil", "host"]
        return bound(SymbolTrack(title="Habitat",
                                 options={"color_column": 0, "size_column": 1,
                                          "thickness": 34}),
                     tree,
                     {n: [groups[i % 3], float(rngs.randint(1, 30))]
                      for i, n in enumerate(tips(tree))},
                     ["habitat", "count"])

    def range_track(tree):
        internal = [n for n in tree.nodes
                    if n.children and n.parent is not None][:3]
        track = CladeRangeTrack(title="Named clades",
                                options={"show_labels": True})
        track.data.columns = ["color", "label"]
        track.data.rows = {n.id: [SAFE[i], f"Clade {chr(65 + i)}"]
                           for i, n in enumerate(internal)}
        return track

    def genes_track(tree):
        genes = ["ampC", "blaZ", "mecA", "tetK"]
        return bound(BinaryMatrixTrack(title="Genes",
                                       options={"thickness": 62,
                                                "shape": "square"}),
                     tree,
                     {n: [rngs.choice([1, 1, 0, -1]) for _ in genes]
                      for n in tips(tree)}, genes)

    # Deliberately a lot: this is the "can it do all of it at once" answer.
    stack_all = [range_track(bacteria), strip_track(bacteria, rngs),
                 genes_track(bacteria), heatmap_track(bacteria, rngs),
                 bar_track(bacteria, rngs), sym_track(bacteria)]
    figure("showcase-everything-rectangular", S,
           "Six track types on one tree at once: clade ranges, a colour strip, "
           "a binary matrix, a heatmap, a bar chart and sized symbols, with "
           "aligned tips and guide lines.",
           doc_for(bacteria, tracks=stack_all, align_tips=True))

    stack_all_circular = [range_track(bacteria), strip_track(bacteria, rngs),
                          genes_track(bacteria), heatmap_track(bacteria, rngs),
                          bar_track(bacteria, rngs), sym_track(bacteria)]
    figure("showcase-everything-circular", S,
           "The same six tracks wrapped into rings. Nothing in any track "
           "changed; only the layout mode did.",
           doc_for(bacteria, tracks=stack_all_circular,
                   mode=LayoutMode.CIRCULAR, arc=345.0, align_tips=True))

    # ------------------------------------------------------------ 6. corpus
    corpus = ROOT / "examples" / "corpus"
    manifest = corpus / "corpus.json"
    if manifest.is_file():
        print("corpus")
        S = "The corpus"
        import json as _json
        entries = _json.loads(manifest.read_text(encoding="utf-8"))
        suffixes = {"newick": ".nwk", "nexus": ".nex", "phyloxml": ".xml"}
        for entry in entries:
            if entry["tips"] > 400:
                continue  # the scale trees are for timing, not for looking at
            path = corpus / f"{entry['stem']}{suffixes[entry['format']]}"
            if not path.is_file():
                continue
            tree = load_tree(path)
            tracks = [load_annotation(corpus / name, tree)
                      for name in entry["tracks"]]
            # 340 rather than the default 350: the gap is the whole of a
            # fan's header row, and at 350 the microbiome survey's heatmap
            # caption has nowhere to go.  Ignored in rectangular mode.
            mode = (LayoutMode.CIRCULAR if entry["tips"] > 40
                    else LayoutMode.RECTANGULAR)
            branch = (BranchMode.CLADOGRAM_ALIGNED
                      if entry["shape"] in ("star", "polytomous")
                      and "morphology" in entry["stem"]
                      else BranchMode.PHYLOGRAM)
            figure(f"corpus-{entry['stem']}", S,
                   f"{entry['study']} — {entry['note']}",
                   doc_for(tree, tracks=tracks, mode=mode, arc=340.0,
                           branch_mode=branch, align_tips=bool(tracks)))

    write_index()
    print(f"\n{len(INDEX)} figures -> {OUT.relative_to(ROOT).as_posix()}/")
    print("   each as .svg (vector), .pdf (vector, for the manual) and .png")
    return 0


def write_index() -> None:
    """A README so the gallery is browsable on GitHub."""
    lines = [
        "# Gallery",
        "",
        "Every figure here is produced by `python tools/make_gallery.py` from the",
        "trees in `examples/`. Each exists as **`.svg`** and **`.pdf`** (vector) and",
        "**`.png`** (raster). The PNGs are shown below; click any heading link to",
        "open the vector version.",
        "",
        "All data is synthetic — seeded random values and invented taxon names.",
        "Nothing is copied from or derived from any other phylogenetics package;",
        "see [`../../legal/FIXTURES.md`](../../legal/FIXTURES.md).",
        "",
    ]
    section = None
    for stem, sec, caption in INDEX:
        if sec != section:
            lines += [f"## {sec}", ""]
            section = sec
        lines += [f"### [{stem}]({stem}.svg)", "",
                  caption, "",
                  f"![{caption}]({stem}.png)", ""]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

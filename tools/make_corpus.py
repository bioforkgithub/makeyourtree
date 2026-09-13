# SPDX-License-Identifier: MIT
"""Generate the example corpus: the range of trees people actually draw.

Run with ``python tools/make_corpus.py``.  Output goes to ``examples/corpus/``.

**Why generated rather than collected.**  It would be easier to download a
folder of published trees, and it is not allowed.  A published phylogeny is
someone's copyrighted work, a curated collection of them attracts the EU
*sui generis* database right on top of that (Directive 96/9/EC), and
``legal/FIXTURES.md`` forbids shipping either -- a rule that exists because the
provenance record is what underwrites the originality claim in the paper.

Generating them is also simply better here.  Every tree below is reproducible
from its seed, so a figure in the manual can be regenerated exactly years later;
the shapes can be chosen to cover the cases that break renderers rather than
whatever happened to be downloadable; and nothing in the repository has a
licence anyone has to check.

What the corpus is for is coverage in three dimensions at once:

*Shape* -- balanced, ladder, star, unbalanced, ultrametric, polytomous. Between
them these cover the pathological cases: a ladder is what breaks recursive
implementations, a star is a single polytomy of high degree, an ultrametric tree
is what a dated analysis produces.

*Scale* -- 8 tips to 5000, because almost every rendering decision changes with
size and a tool that only ever sees small trees hides its scaling problems.

*Study type* -- an outbreak, a pangenome, a gene family, a morphological
cladogram, a microbiome survey. Not because the software cares, but because
someone deciding whether it fits their work looks for their own kind of data.

Every taxon name here is invented and every value is drawn from a seeded RNG.
Any resemblance to a real dataset is arithmetic.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from makeyourtree.core.tree import Tree  # noqa: E402
from makeyourtree.io import save_tree  # noqa: E402

OUT = ROOT / "examples" / "corpus"

#: One seed per entry, so a single tree can be regenerated without disturbing
#: the others. Changing a seed changes only its own file.
INDEX: list[dict] = []


# ------------------------------------------------------------------- shapes


def balanced(n: int, rng: random.Random, length: float = 0.1) -> Tree:
    """A perfectly bifurcating tree: the baseline for layout geometry."""
    tree = Tree()
    live = [tree.new_node(f"T{i:03d}", length) for i in range(n)]
    while len(live) > 1:
        nxt = []
        for i in range(0, len(live) - 1, 2):
            parent = tree.new_node(None, length)
            parent.add_child(live[i])
            parent.add_child(live[i + 1])
            nxt.append(parent)
        if len(live) % 2:
            nxt.append(live[-1])
        live = nxt
    tree.root.add_child(live[0])
    return _finish(tree)


def ladder(n: int, rng: random.Random) -> Tree:
    """A caterpillar: maximal depth, and the shape that breaks recursion.

    Root-to-tip path length equals the tip count, so a recursive traversal
    fails here at a few thousand nodes while an iterative one does not notice.
    """
    tree = Tree()
    node = tree.new_node("T000", 0.1)
    for i in range(1, n):
        parent = tree.new_node(None, 0.05)
        parent.add_child(node)
        parent.add_child(tree.new_node(f"T{i:03d}", 0.1))
        node = parent
    tree.root.add_child(node)
    return _finish(tree)


def star(n: int, rng: random.Random) -> Tree:
    """A single polytomy of degree *n*: no resolution at all."""
    tree = Tree()
    for i in range(n):
        tree.root.add_child(tree.new_node(f"T{i:03d}",
                                          round(rng.uniform(0.05, 1.0), 4)))
    return _finish(tree)


def unbalanced(n: int, rng: random.Random, rate: float = 1.0,
               support: bool = False) -> Tree:
    """Random joining: the shape most real analyses produce."""
    tree = Tree()
    live = [tree.new_node(f"T{i:03d}", round(rng.expovariate(rate * 4) + 0.02, 4))
            for i in range(n)]
    while len(live) > 2:
        a = live.pop(rng.randrange(len(live)))
        b = live.pop(rng.randrange(len(live)))
        parent = tree.new_node(None, round(rng.expovariate(rate) + 0.01, 4))
        if support:
            parent.support = float(rng.randint(50, 100))
        parent.add_child(a)
        parent.add_child(b)
        live.append(parent)
    for node in live:
        tree.root.add_child(node)
    return _finish(tree)


def ultrametric(n: int, rng: random.Random, depth: float = 1.0) -> Tree:
    """Every tip equidistant from the root: what a dated analysis gives.

    Built by coalescing backwards in time, so the tip-to-root distance is equal
    by construction rather than by adjustment afterwards.
    """
    tree = Tree()
    live = [(tree.new_node(f"T{i:03d}", 0.0), 0.0) for i in range(n)]
    time = 0.0
    while len(live) > 1:
        time += depth / max(1, len(live) - 1) * rng.uniform(0.5, 1.5)
        i = rng.randrange(len(live))
        a, a_time = live.pop(i)
        j = rng.randrange(len(live))
        b, b_time = live.pop(j)
        a.branch_length = round(time - a_time, 5)
        b.branch_length = round(time - b_time, 5)
        parent = tree.new_node(None, 0.0)
        parent.add_child(a)
        parent.add_child(b)
        live.append((parent, time))
    node, node_time = live[0]
    node.branch_length = 0.0
    tree.root.add_child(node)
    return _finish(tree)


def polytomous(n: int, rng: random.Random) -> Tree:
    """Mostly resolved with a few genuine polytomies, as a consensus tree is."""
    tree = unbalanced(n, rng)
    internal = [x for x in tree.nodes if x.children and x.parent is not None]
    for node in internal[: max(1, len(internal) // 6)]:
        parent = node.parent
        if parent is None:
            continue
        for child in list(node.children):
            node.remove_child(child)
            parent.add_child(child)
        parent.remove_child(node)
    return _finish(tree)


def _finish(tree: Tree) -> Tree:
    tree.root.name = None
    tree.rooted = True
    tree.refresh()
    return tree


# -------------------------------------------------------------------- tracks


def mytrack(track_type: str, title: str, columns, rows, *, options=None,
            colors=None, legend=None, match=None) -> str:
    out = ["#makeyourtree-annotation 1", "", "[track]",
           f"type = {track_type}", f"title = {title}"]
    if match:
        out.append(f"match = {match}")
    if options:
        out += ["", "[options]"] + [f"{k} = {v}" for k, v in options.items()]
    out += ["", "[columns]", "names = " + ", ".join(columns)]
    if colors:
        out += ["", "[colors]"] + [f"{k} = {v}" for k, v in colors.items()]
    if legend:
        out += ["", "[legend]"] + [f"{k} = {v}" for k, v in legend.items()]
    out += ["", "[data]"]
    for key, values in rows:
        out.append("\t".join([key] + [str(v) for v in values]))
    return "\n".join(out) + "\n"


SAFE = ("#117733", "#DDCC77", "#CC6677", "#332288", "#AA4499",
        "#88CCEE", "#44AA99", "#999933")


def write(name: str, text: str) -> None:
    (OUT / name).write_text(text, encoding="utf-8", newline="\n")


def record(stem: str, shape: str, tips: int, seed: int, fmt: str,
           study: str, note: str, tracks: list[str]) -> None:
    INDEX.append({"stem": stem, "shape": shape, "tips": tips, "seed": seed,
                  "format": fmt, "study": study, "note": note,
                  "tracks": tracks})


def tips_of(tree: Tree) -> list[str]:
    return [n.name for n in tree.nodes if not n.children and n.name]


def emit(stem: str, tree: Tree, *, shape: str, seed: int, study: str,
         note: str, fmt: str = "newick", tracks: list[tuple[str, str]] = ()) -> None:
    """Write one tree and its annotation files, and record it in the index."""
    suffix = {"newick": ".nwk", "nexus": ".nex", "phyloxml": ".xml"}[fmt]
    # phyloXML carries rootedness in the document structure, so it takes no
    # `rooting` option; passing one is a TypeError rather than a no-op.
    options = {"support": True}
    if fmt in ("newick", "nexus"):
        options["rooting"] = True
    save_tree(tree, OUT / f"{stem}{suffix}", format=fmt, **options)
    names = []
    for track_name, body in tracks:
        write(f"{stem}_{track_name}.mytrack", body)
        names.append(f"{stem}_{track_name}.mytrack")
    record(stem, shape, len(tips_of(tree)), seed, fmt, study, note, names)
    print(f"  {stem:<28} {shape:<12} {len(tips_of(tree)):>6} tips  {study}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="make-corpus",
        description="Generate the example tree corpus.")
    parser.add_argument("--skip-large", action="store_true",
                        help="omit the trees above 1000 tips, which dominate "
                             "the run time")
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    print("shapes")

    # ------------------------------------------------------------- 1. shapes
    emit("shape-balanced", balanced(32, random.Random(1)),
         shape="balanced", seed=1, study="Shape reference",
         note="Perfectly bifurcating. The baseline for layout geometry.")
    emit("shape-ladder", ladder(40, random.Random(2)),
         shape="ladder", seed=2, study="Shape reference",
         note="A caterpillar. Root-to-tip depth equals the tip count, which is "
              "what breaks a recursive traversal.")
    emit("shape-star", star(24, random.Random(3)),
         shape="star", seed=3, study="Shape reference",
         note="One polytomy of degree 24: no internal resolution at all.")
    emit("shape-unbalanced", unbalanced(40, random.Random(4), support=True),
         shape="unbalanced", seed=4, study="Shape reference",
         note="Random joining with support values, the shape most analyses "
              "produce.")
    emit("shape-ultrametric", ultrametric(30, random.Random(5)),
         shape="ultrametric", seed=5, study="Shape reference",
         note="Every tip equidistant from the root, as a dated analysis gives.")
    emit("shape-polytomous", polytomous(36, random.Random(6)),
         shape="polytomous", seed=6, study="Shape reference",
         note="Mostly resolved with genuine polytomies, as a consensus tree is.")

    # -------------------------------------------------------------- 2. scale
    print("scale")
    for n, seed in ((8, 10), (60, 11), (250, 12)):
        emit(f"scale-{n:04d}", unbalanced(n, random.Random(seed), support=True),
             shape="unbalanced", seed=seed, study="Scale reference",
             note=f"{n} tips. Almost every rendering decision changes with "
                  f"size; this is the series for checking that.")
    if not args.skip_large:
        for n, seed in ((1000, 13), (5000, 14)):
            emit(f"scale-{n:04d}", unbalanced(n, random.Random(seed)),
                 shape="unbalanced", seed=seed, study="Scale reference",
                 note=f"{n} tips. Label rendering has to be turned off around "
                      f"here, and a circular layout starts to pay off.")

    # --------------------------------------------------------- 3. study types
    print("study types")
    rng = random.Random(100)
    outbreak = ultrametric(48, rng)
    names = tips_of(outbreak)
    lineages = ["B.1", "B.1.1", "AY.4", "BA.2"]
    emit("study-outbreak", outbreak,
         shape="ultrametric", seed=100, study="Outbreak / dated phylogeny",
         note="A time-scaled tree with lineage assignments and sampling dates: "
              "the commonest epidemiological figure.",
         tracks=[
             ("lineage", mytrack(
                 "color-strip", "Lineage", ["lineage"],
                 [(n, [lineages[i % 4]]) for i, n in enumerate(names)],
                 options={"thickness": 16},
                 colors={l: SAFE[i] for i, l in enumerate(lineages)},
                 legend={"title": "Lineage", "show": "true"})),
             ("date", mytrack(
                 "gradient", "Sampling date", ["day"],
                 [(n, [rng.randint(0, 720)]) for n in names],
                 options={"thickness": 16},
                 legend={"title": "Days since index case", "show": "true"})),
         ])

    rng = random.Random(101)
    pangenome = unbalanced(36, rng, rate=2.0, support=True)
    names = tips_of(pangenome)
    genes = ["ampC", "blaZ", "mecA", "tetK", "ermB", "vanA", "aacA", "sul1"]
    emit("study-pangenome", pangenome,
         shape="unbalanced", seed=101, study="Bacterial pangenome",
         note="Gene presence and absence across strains, with a genome-size "
              "bar. Unknown is a third state and is drawn as a gap.",
         tracks=[
             ("genes", mytrack(
                 "binary-matrix", "Resistance genes", genes,
                 [(n, [rng.choice([1, 1, 0, 0, -1]) for _ in genes])
                  for n in names],
                 options={"thickness": 110, "shape": "square"},
                 legend={"title": "Gene present", "show": "true"})),
             ("size", mytrack(
                 "bar-chart", "Genome size (Mb)", ["Mb"],
                 [(n, [round(rng.uniform(2.4, 6.1), 2)]) for n in names],
                 options={"thickness": 80, "color": "#4C7A9C", "axis": "true"})),
         ])

    rng = random.Random(102)
    microbiome = unbalanced(45, rng)
    names = tips_of(microbiome)
    sites = ["gut", "skin", "oral", "soil", "marine"]
    emit("study-microbiome", microbiome,
         shape="unbalanced", seed=102, study="Microbiome survey",
         note="Relative abundance across body sites, as a heatmap, with the "
              "composition of each taxon beside it.",
         tracks=[
             ("abundance", mytrack(
                 "heatmap", "Relative abundance (log)", sites,
                 [(n, [round(rng.gauss(0, 1.3), 2) for _ in sites])
                  for n in names],
                 options={"cell_size": 20, "normalize": "global",
                          "color_min": "#2166AC", "color_mid": "#F7F7F7",
                          "color_max": "#B2182B"},
                 legend={"title": "log abundance", "show": "true"})),
             ("composition", mytrack(
                 "pie-chart", "Read composition", ["A", "B", "C"],
                 [(n, [rng.uniform(1, 8), rng.uniform(1, 8), rng.uniform(1, 8)])
                  for n in names],
                 options={"radius": 7.0})),
         ])

    rng = random.Random(103)
    family = unbalanced(28, rng, support=True)
    names = tips_of(family)
    emit("study-gene-family", family,
         shape="unbalanced", seed=103, study="Gene family",
         note="A protein family with its domain architecture drawn to scale "
              "along each sequence.",
         tracks=[
             ("domains", mytrack(
                 "domain-architecture", "Architecture",
                 ["length", "f1", "f2", "f3"],
                 [(n, [480,
                       f"{15 + 3 * i}|{150 + 3 * i}|rect|#CC6677|Kinase",
                       f"{190 + 2 * i}|{300 + 2 * i}|ellipse|#332288|SH2",
                       f"{330 + 4 * i}|460|hexagon|#117733|PDZ"])
                  for i, n in enumerate(names)],
                 options={"thickness": 230, "length_column": 0,
                          "feature_height": 12, "show_labels": "true"})),
         ])

    rng = random.Random(104)
    morpho = polytomous(22, rng)
    for node in morpho.nodes:
        node.branch_length = None
    morpho.refresh()
    emit("study-morphology", morpho,
         shape="polytomous", seed=104, study="Morphological cladogram",
         note="No branch lengths at all, and real polytomies. Must be drawn as "
              "a cladogram; a phylogram would imply distances that do not exist.",
         tracks=[
             ("traits", mytrack(
                 "binary-matrix", "Character states",
                 ["wings", "scales", "jaws", "limbs"],
                 [(n, [rng.choice([1, 0]) for _ in range(4)])
                  for n in tips_of(morpho)],
                 options={"thickness": 70, "shape": "circle"})),
         ])

    rng = random.Random(105)
    biogeo = unbalanced(34, rng)
    names = tips_of(biogeo)
    regions = ["Neotropic", "Afrotropic", "Palearctic", "Indomalayan",
               "Australasia"]
    emit("study-biogeography", biogeo,
         shape="unbalanced", seed=105, study="Biogeography",
         note="Regions per tip plus dispersal events drawn as curved links "
              "between arbitrary taxa.",
         tracks=[
             ("region", mytrack(
                 "color-strip", "Region", ["region"],
                 [(n, [regions[i % 5]]) for i, n in enumerate(names)],
                 options={"thickness": 18},
                 colors={r: SAFE[i] for i, r in enumerate(regions)},
                 legend={"title": "Region", "show": "true"})),
             ("dispersal", mytrack(
                 "connections", "Dispersal events",
                 ["from", "to", "weight", "color", "style", "label"],
                 [(str(i), [names[i * 5 % len(names)],
                            names[(i * 7 + 3) % len(names)],
                            round(rng.uniform(0.5, 3.0), 2), SAFE[i % 5], "-",
                            f"event {i + 1}"])
                  for i in range(5)],
                 options={"bow": 0.5, "show_labels": "true"})),
         ])

    # ------------------------------------------------------------ 4. formats
    print("formats")
    rng = random.Random(200)
    for fmt in ("nexus", "phyloxml"):
        tree = unbalanced(18, random.Random(200), support=True)
        emit(f"format-{fmt}", tree, shape="unbalanced", seed=200,
             study="Format reference", fmt=fmt,
             note=f"The same tree written as {fmt}, so every reader has "
                  f"something to open.")

    write_index()
    print(f"\n{len(INDEX)} trees -> {OUT.relative_to(ROOT).as_posix()}/")
    return 0


def write_index() -> None:
    (OUT / "corpus.json").write_text(
        json.dumps(INDEX, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Tree corpus",
        "",
        "Trees spanning the range people actually draw, in three dimensions:",
        "**shape**, **scale** and **study type**. Regenerate with",
        "`python tools/make_corpus.py`.",
        "",
        "Everything here is **generated from a seed**, and every taxon name is",
        "invented. Nothing is downloaded, because a published phylogeny is",
        "someone's copyrighted work and a collection of them attracts the EU",
        "database right on top of that -- see",
        "[`../../legal/FIXTURES.md`](../../legal/FIXTURES.md). Generating them",
        "also means every one is reproducible exactly, years later, from the",
        "seed recorded below.",
        "",
        "| Tree | Shape | Tips | Format | Study type | Seed | Tracks |",
        "|---|---|---:|---|---|---:|---:|",
    ]
    for item in INDEX:
        lines.append(
            f"| `{item['stem']}` | {item['shape']} | {item['tips']} | "
            f"{item['format']} | {item['study']} | {item['seed']} | "
            f"{len(item['tracks'])} |")
    lines += ["", "## Notes", ""]
    for item in INDEX:
        lines.append(f"- **`{item['stem']}`** — {item['note']}")
    lines.append("")
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

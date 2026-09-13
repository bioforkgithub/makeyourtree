# SPDX-License-Identifier: MIT
"""Regenerate every file in this directory.

Run with ``python examples/generate.py``.  The output is deterministic: each
dataset is built from its own seeded :class:`random.Random`, so re-running this
script reproduces the committed files byte for byte.

Everything here is synthetic: a seeded RNG, a Yule-style birth process and
made-up taxon names.  Nothing is copied from, derived from, or checked against
any other phylogenetics package's bundled data.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from makeyourtree.core.tree import Tree
from makeyourtree.io import save_tree

OUT = Path(__file__).resolve().parent
OUT.mkdir(exist_ok=True)


def yule_tree(names, rng, *, rate=1.0, support=False):
    """A random bifurcating tree over *names* by repeated random joining.

    Coalescent-style: repeatedly pick two live lineages, join them under a new
    parent, and give the new edge an exponential waiting time.  Produces a
    plausible-looking phylogram without reproducing anyone's data.
    """
    tree = Tree()
    live = []
    for name in names:
        node = tree.new_node(name, round(rng.expovariate(rate * 4) + 0.02, 4))
        live.append(node)
    while len(live) > 2:
        a = live.pop(rng.randrange(len(live)))
        b = live.pop(rng.randrange(len(live)))
        parent = tree.new_node(None, round(rng.expovariate(rate) + 0.01, 4))
        if support:
            parent.support = float(rng.randint(55, 100))
        parent.add_child(a)
        parent.add_child(b)
        live.append(parent)
    for node in live:
        tree.root.add_child(node)
    tree.root.name = None
    tree.rooted = True
    tree.refresh()
    return tree


def write(name: str, text: str) -> None:
    (OUT / name).write_text(text, encoding="utf-8", newline="\n")
    print("wrote", name)


def mytrack(track_type, title, columns, rows, *, options=None, colors=None,
         legend=None, match=None):
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
    for key, vals in rows:
        out.append("\t".join([key] + [str(v) for v in vals]))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 1. primates
rng = random.Random(20260820)
GENERA = ["Aotus", "Cebus", "Saimiri", "Callithrix", "Ateles", "Alouatta",
          "Macaca", "Papio", "Cercopithecus", "Colobus", "Hylobates",
          "Pongo", "Gorilla", "Pan", "Homo", "Lemur"]
SPECIES = [f"{g}_{s}" for g, s in zip(GENERA, [
    "trivirgatus", "capucinus", "sciureus", "jacchus", "geoffroyi", "palliata",
    "mulatta", "anubis", "mitis", "guereza", "lar", "abelii", "beringei",
    "troglodytes", "sapiens", "catta"])]
t1 = yule_tree(SPECIES, rng, support=True)
save_tree(t1, OUT / "primates.nwk", format="newick", support=True, rooting=True)

REGION = {n: r for n, r in zip(SPECIES, [
    "Neotropic", "Neotropic", "Neotropic", "Neotropic", "Neotropic", "Neotropic",
    "Palearctic", "Afrotropic", "Afrotropic", "Afrotropic", "Indomalayan",
    "Indomalayan", "Afrotropic", "Afrotropic", "Palearctic", "Madagascar"])}
write("primates_region.mytrack", mytrack(
    "color-strip", "Biogeographic region", ["region"],
    [(n, [REGION[n]]) for n in SPECIES],
    options={"thickness": 18, "border_width": 0.5},
    colors={"Neotropic": "#117733", "Afrotropic": "#DDCC77",
            "Indomalayan": "#CC6677", "Palearctic": "#332288",
            "Madagascar": "#AA4499"},
    legend={"title": "Region", "show": "true"}))

write("primates_bodymass.mytrack", mytrack(
    "bar-chart", "Body mass (kg)", ["mass"],
    [(n, [round(rng.uniform(0.3, 160.0), 1)]) for n in SPECIES],
    options={"thickness": 90, "color": "#4C7A9C", "axis": "true"},
    legend={"title": "Body mass", "show": "true"}))

# --------------------------------------------------------------- 2. bacteria
rng2 = random.Random(7)
STRAINS = [f"strain_{i:02d}" for i in range(1, 25)]
t2 = yule_tree(STRAINS, rng2, rate=2.0, support=True)
save_tree(t2, OUT / "bacteria.nwk", format="newick", support=True, rooting=True)

GENES = ["ampC", "blaZ", "mecA", "tetK", "ermB", "vanA"]
write("bacteria_resistance.mytrack", mytrack(
    "binary-matrix", "Resistance genes", GENES,
    [(s, [rng2.choice([1, 1, 0, 0, -1]) for _ in GENES]) for s in STRAINS],
    options={"thickness": 90, "shape": "square"},
    legend={"title": "Gene present", "show": "true"}))

write("bacteria_expression.mytrack", mytrack(
    "heatmap", "Expression (log2)", ["0h", "2h", "6h", "12h", "24h"],
    [(s, [round(rng2.gauss(0, 1.4), 2) for _ in range(5)]) for s in STRAINS],
    options={"cell_size": 22, "normalize": "global", "color_min": "#2166AC",
             "color_mid": "#F7F7F7", "color_max": "#B2182B"},
    legend={"title": "log2 fold change", "show": "true"}))

# ------------------------------------------------------------ 3. tiny cladogram
t3 = Tree()
t3.root.name = "life"
euk = t3.new_node("Eukaryota", 1.0)
bac = t3.new_node("Bacteria", 1.0)
arc = t3.new_node("Archaea", 1.0)
for n in (bac, arc, euk):
    t3.root.add_child(n)
for parent, kids in ((euk, ["Plantae", "Fungi", "Metazoa"]),
                     (bac, ["Firmicutes", "Proteobacteria"]),
                     (arc, ["Euryarchaeota", "Crenarchaeota"])):
    for k in kids:
        parent.add_child(t3.new_node(k, 1.0))
t3.rooted = True
t3.refresh()
save_tree(t3, OUT / "domains.nwk", format="newick", rooting=True)

write("domains_labels.mytrack", mytrack(
    "text-labels", "Notes", ["note"],
    [("Plantae", ["photosynthetic"]), ("Fungi", ["osmotrophic"]),
     ("Metazoa", ["ingestive"]), ("Firmicutes", ["low GC"]),
     ("Proteobacteria", ["gram-negative"]),
     ("Euryarchaeota", ["methanogens"]), ("Crenarchaeota", ["thermophiles"])],
    options={"size": 10, "color": "#5A5A66"}))

# ---------------------------------------------- 4. multi-format: nexus + phyloxml
rng3 = random.Random(99)
VIRUS = [f"isolate_{c}{i}" for c in "AB" for i in range(1, 7)]
t4 = yule_tree(VIRUS, rng3, rate=3.0, support=True)
save_tree(t4, OUT / "virus.nex", format="nexus", support=True)
save_tree(t4, OUT / "virus.xml", format="phyloxml", support=True)

write("virus_lineage.mytrack", mytrack(
    "color-strip", "Lineage", ["lineage"],
    [(v, ["A" if "_A" in v else "B"]) for v in VIRUS],
    colors={"A": "#E69F00", "B": "#0072B2"},
    legend={"title": "Lineage", "show": "true"}))
write("virus_titre.mytrack", mytrack(
    "gradient", "Titre (log10)", ["titre"],
    [(v, [round(rng3.uniform(1.0, 7.5), 2)]) for v in VIRUS],
    options={"thickness": 20},
    legend={"title": "Titre", "show": "true"}))
print("done")

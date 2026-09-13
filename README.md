# MakeYourTree

**A standalone desktop studio for visualising and annotating phylogenetic trees.**

MakeYourTree runs entirely on your machine. There is no server, no account, no upload, and no
network access at runtime — your trees and your unpublished data never leave your computer.

---

## What it does

**Reads what you already have**
Newick, New Hampshire eXtended (NHX), NEXUS (with `TRANSLATE` blocks and `[&R]`/`[&U]`
rooting hints), and phyloXML. Parsing is deliberately forgiving: real files break the
specs constantly, so MakeYourTree loads them anyway and tells you what it had to fix.

**Draws it five ways**
Rectangular and slanted phylograms and cladograms, circular fans with a configurable arc
and inner radius, circular cladograms, and unrooted layouts using Felsenstein's
equal-angle and equal-daylight algorithms.

**Lets you edit the tree**
Reroot on any branch, by outgroup, or at the midpoint. Ladderize, rotate, collapse and
expand clades, prune taxa, extract subtrees. Everything is undoable.

**Annotates it**
Thirteen track types stack alongside the tree: clade highlights, colour strips, binary
symbol matrices, gradients, heatmaps, bar charts (grouped and stacked), box plots, pie
and donut charts, protein domain architectures, external text labels, sized symbols, line
charts, and curved connections between arbitrary nodes.

Every track is written once against a **band-space projector** and therefore works in
every *rooted* layout mode — a heatmap wraps into an annulus in circular mode with no
separate code path, and labels flip so they stay right-way-up on the left half of the fan.

The exception is unrooted layouts, which have no tip ordering for band space to use. There
tracks are drawn as a column beside the figure, aligned to nothing. Use a rooted layout if
you need annotation.

**Saves your work**
A project file (`.mytree`) keeps the tree, the layout, the theme and every annotation
track together, so a figure can be reopened and corrected months later instead of being
rebuilt from parts.

**Exports honestly**
SVG and PDF as vectors, PNG at any resolution. The on-screen canvas and the exported file
consume the identical scene description, so what you export is what you saw.

---

## Install

The same commands work on Windows, macOS and Linux — the environment resolves the platform
differences, including the Qt system libraries Linux would otherwise need installed by
hand. MakeYourTree is not on PyPI; install from source:

```bash
git clone https://github.com/bioforkgithub/makeyourtree.git
cd makeyourtree
conda env create -f environment.yml     # or: mamba env create -f environment.yml
conda activate makeyourtree
pip install -e . --no-deps
```

Prefer pip and `venv`? That works too, and needs Python 3.12+:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[studio]"
```

Launch the application:

```bash
makeyourtree-studio
```

Or use the core from the command line, with no GUI toolkit needed:

```bash
makeyourtree info tree.nwk
makeyourtree convert tree.nex tree.xml
makeyourtree render tree.nwk figure.svg --mode circular --track hosts.mytrack
makeyourtree render tree.nwk figure.png --dpi 600 --width 180mm
makeyourtree render tree.nwk figure.pdf --page a4 --landscape
makeyourtree reroot tree.nwk rooted.nwk --midpoint
```

`render` writes **SVG, PDF or PNG** — chosen from the output extension, or with
`--output-format`. `--dpi` sets raster resolution (default 300). `--width` and
`--height` take real units (`180mm`, `7in`, `900pt`, `1200px`), and `--page`
offers named sizes including single- and double-column journal widths. PNG and
PDF need the `studio` extra, which supplies the rasteriser; SVG needs nothing
beyond the library.

**[`INSTALL.md`](INSTALL.md) has the full walkthrough** — both routes step by step, how to
install the library alone without Qt, how to build a standalone bundle, platform notes and
a troubleshooting table.

The core depends only on NumPy; the studio adds PySide6.

---

## Use it as a library

The core has **no GUI-toolkit dependency**, so it works in scripts, notebooks and CI.

```python
from makeyourtree import load_tree
from makeyourtree.doc import Document
from makeyourtree.layout import LayoutParams, LayoutMode
from makeyourtree.scene import compose
from makeyourtree.render import render_svg
from makeyourtree.ops import midpoint_root, ladderize

tree = load_tree("tree.nwk")
midpoint_root(tree).apply(tree)
ladderize(tree).apply(tree)

doc = Document(tree=tree, params=LayoutParams(mode=LayoutMode.CIRCULAR, arc=340))
open("figure.svg", "w").write(render_svg(compose(doc)))
```

---

## Not sure what figure you want?

Most people arrive with a tree, some metadata and a destination, not a design.
Two ways to get from there to a figure:

```bash
makeyourtree guide                                    # answer a few questions
makeyourtree guide --from-figure paper-figure.pdf     # or start from a figure you like
```

Either produces a **step-by-step plan** with the exact commands for your data,
saved as a `.myplan` file. Stop whenever you like and pick it up days later:

```bash
makeyourtree plan figure.myplan                 # what is next
makeyourtree plan figure.myplan --done 1        # tick a step off
makeyourtree plan figure.myplan --export plan.md  # a Markdown checklist
```

In the application it is **Help ▸ Guide Me** (F1), and **Help ▸ Resume a Plan**
to carry on.

`--from-figure` reads a PDF or image and *measures* it — whether the ink is
arranged as a fan, how much saturated colour there is, how many distinct hues.
It reports what it found with the evidence and its confidence, pre-fills only
what it can support, and asks you about the rest. It does not "recognise" the
figure and it sends nothing anywhere: like everything else here, it runs
entirely on your machine.

---

## Gallery and manual

**[Browse the gallery](examples/gallery/)** --- 49 figures covering every layout
mode, all thirteen annotation track types, the main features, and a
**combine-everything showcase** putting six track types on one tree at once (as
concentric rings in circular mode). Each is available as SVG, PDF and PNG.

**[The tree corpus](examples/corpus/)** --- 19 trees spanning the range people
actually draw: six *shapes* (balanced, ladder, star, unbalanced, ultrametric,
polytomous), five *scales* from 8 to 5000 tips, and six *study types* (outbreak,
pangenome, microbiome, gene family, morphological cladogram, biogeography), in
Newick, NEXUS and phyloXML. Every one is generated from a recorded seed, so it is
reproducible exactly --- nothing is downloaded, because a published phylogeny is
someone's copyrighted work.

**Video tutorial** --- a fifteen-minute walkthrough covering installation, the
interface, annotation and export.
<!-- TODO: replace with the real YouTube URL once the video is public. The
shooting script, the demo-reset helper and the listing text are in docs/video/. -->
*(link to follow)*

**[Download the user manual (PDF)](docs/manual/MakeYourTree-Manual.pdf)** --- 61
pages, with a clickable contents page and PDF bookmarks, covering installation,
the interface, every layout, the annotation format, all thirteen track types, the
command line, the Python API, keyboard shortcuts and troubleshooting. (It predates
the `guide`/`plan` commands, which are documented in this README and in `--help`.) Rebuild it
with `python docs/manual/build.py`.

---

## Design

Three ideas carry the architecture.

**Two independent coordinates.** Every layout is a *cross* coordinate (`y`, or angle)
derived only from tip order, and an *along* coordinate (`x`, or radius) derived only from
branch length or depth. Reordering children touches one; rescaling touches the other.

**Band space.** Tracks are written in `(row, offset)` coordinates and never compute a
scene position. A projector maps band space to the plane — affine in linear layouts, polar
in circular ones. One track implementation therefore serves every layout mode.

**One scene, many backends.** Layout and composition produce a plain data `Scene`. The Qt
canvas and the pure-Python SVG writer both consume it, so the screen and the export cannot
drift apart.

Details in [`docs/SPEC.md`](docs/SPEC.md).

---

## Licensing

**MakeYourTree is free and open-source software, MIT-licensed throughout** — the library, the
command-line interface and the desktop application alike. Use it, modify it, redistribute
it, build on it; keep the copyright notice and accept that it comes with no warranty.
Full text in [`LICENSE`](LICENSE).

The application links PySide6/Qt, which is LGPLv3 in its open-source edition. That places
no restriction on *using* MakeYourTree or on reading its source. It does place conditions on
anyone **redistributing a compiled bundle** — the licence texts must travel with it, and
Qt must ship as replaceable shared libraries, which is why the build is PyInstaller
`--onedir` rather than `--onefile`. [`LICENSE.md`](LICENSE.md) documents each condition,
and `tests/test_licensing.py` enforces the rules on every build.

**Your figures are yours.** MakeYourTree claims no rights in the trees you load or the output
you export, and imposes no attribution requirement on them.

---

## AI disclosure

I wrote parts of the source code, the test suite and the documentation with the
assistance of a large language model (Anthropic Claude), used as a tool under my
direction. I specified the architecture and the interface contracts, directed the
implementation, reviewed the code, and I am responsible for the whole of the software.

Every number quoted in the documentation came from running the program, not from a
language model. No artificial intelligence system is an author here, and none holds
copyright in this work.

---

## Related work

Interactive phylogenetic tree visualisation has a long published history, and citing it is
good scholarly practice. Notable prior work includes iTOL (Letunic & Bork, *Nucleic Acids
Research*, 2007–2024), Dendroscope (Huson & Scornavacca, 2012), FigTree, the ETE Toolkit
(Huerta-Cepas et al., 2016), ggtree (Yu et al., 2017) and Archaeopteryx (Zmasek).
MakeYourTree shares the problem domain with these tools and none of their code. Every
format and algorithm here is implemented from its published specification or from the
primary literature, cited in the module that implements it.

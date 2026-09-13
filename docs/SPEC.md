# MakeYourTree — implementation specification v1

**MakeYourTree** is a standalone, offline desktop studio for visualising and annotating
phylogenetic trees. It is a native application, not a web app: no server, no hosting,
no network access at runtime.

- `makeyourtree` — core library. Parsers, tree model, layout engine, annotation model,
  scene graph, SVG renderer, CLI. **Zero Qt imports.** License: **MIT**.
- `makeyourtree_studio` — the desktop application. PySide6/Qt6. License: **MIT**.

MakeYourTree is **free and open-source software, MIT throughout**. The split between the two
packages is architectural, not legal: the core stays toolkit-free so it can be embedded
and tested headlessly. `tests/test_licensing.py` enforces the rules below and fails the
build on a breach — read it before touching anything licence-adjacent.

**Non-negotiable, because they are what make distributing a build lawful:**
1. **Nothing under `src/makeyourtree/` may import PySide6 or PyQt.** The MIT core stays
   toolkit-free.
2. **Never import Qt Charts, Qt Data Visualization or Qt Virtual Keyboard.** They are
   GPL-3.0-only in the open-source Qt edition and would force the entire product to GPL.
   Chart-like output comes from our own track renderers in `makeyourtree.tracks`.
3. **Qt ships unmodified**, dynamically linked. Packaging uses PyInstaller `--onedir`,
   never `--onefile` — a user must be able to swap in their own Qt build (LGPL-3.0 §4(d)(1)).
4. Studio must expose **Help ▸ Third-Party Licences** at runtime, reproducing
   `THIRD-PARTY-NOTICES.md` and the bundled licence texts (LGPL-3.0 §4(a), §4(c)).

Python 3.12. Runtime dependencies of the core: `numpy` only. The studio adds `PySide6`.

---

## 1. What may be implemented, and from what

Every format and algorithm here is written from its published specification or from
the primary literature, cited in the module that implements it. Functionality,
algorithms and
**file formats are not copyrightable** (*SAS Institute v. World Programming*, 64 F.4th 1319
(Fed. Cir. 2023); CJEU C-406/10; *Google v. Oracle*, 2021; *Lotus v. Borland*). Copying
expression is a different matter and is forbidden.

**DO**
1. Implement Newick, NHX, NEXUS, PhyloXML, CSV/TSV, SVG, PNG and PDF freely and completely —
   all are published open specifications.
2. Derive layout mathematics from first principles and cite the paper or textbook in a
   module docstring (Felsenstein's equal-angle and equal-daylight; Heckbert's nice-number
   labelling; Reingold–Tilford-style tidy layout).
3. Generate your own test fixtures synthetically, or take them from openly licensed sources
   with its licence recorded beside it.
4. Use permissively licensed assets only (Lucide/Tabler/Feather icons — MIT; OFL fonts) and
   record SPDX ids in `THIRD-PARTY-NOTICES.md`.
5. Design our own visual identity: our own palette, panel arrangement, iconography and
   option vocabulary.

**DON'T**
1. Don't open, view-source, save, beautify or debug any other product's shipped JavaScript,
   CSS or binaries. Not once, not "just to check".
2. Don't copy help text, tooltips, error messages or documentation prose from another
   product — not verbatim, not paraphrased, not structurally.
3. Don't ship, vendor or quote another product's annotation template files, and don't reuse
   their directive keyword vocabulary. Our annotation format is specified in
   `src/makeyourtree/annot/table.py` and its keywords are **ours**.
4. Don't use another product's bundled example trees or demo datasets as fixtures
   (copyright, plus the EU database right, Directive 96/9/EC).
5. Don't reproduce, trace or redraw any other product's icons, buttons or logo.
6. Don't name the product, modules, classes, options or CLI flags after another product's
   branding. A factual interop module name (`import_foreign.py`) is fine; a branded one is not.
7. Don't verify our output by comparing it against another product's output. Verify against
   the published format specifications and against independently licensed open-source tools.

Every user-facing mention of a comparable product must carry: *"Independent project; not
affiliated with, endorsed by, or derived from any other phylogenetics package."*

---

## 2. The contracts — already written, do not change

These files exist and are **frozen**. Read them before implementing anything; they are the
API every unit codes against. Changing a signature here requires a spec amendment, not a
local workaround.

| File | What it fixes |
|---|---|
| `core/node.py` | `Node`. **`branch_length` and `support` belong to the EDGE `parent → self`.** Any operation reversing an edge must carry them with it. |
| `core/tree.py` | `Tree`: id/name indexes, `refresh()` deriving `n_leaves`/`height`/`depth_len`/`level`, `mrca`, `distance`, `path`, `search`, `copy`. |
| `core/traversal.py` | Iterative `preorder`/`postorder`/`levelorder`/`iter_leaves`. **Never recurse** — a 100k-leaf caterpillar tree blows the stack. `visible_only=True` skips `hidden` subtrees and does not descend into `collapsed` nodes. |
| `core/diagnostics.py` | `DiagnosticSink`. Parsers are **lenient**: record a diagnostic and carry on, don't raise. |
| `layout/params.py` | `LayoutParams`, `LayoutMode`, `BranchMode`, `ParentRule`, `UnrootedMethod`, `CollapseShape`. |
| `layout/frame.py` | `LayoutFrame` — flat parallel arrays plus flat edge coordinate lists. `Layout` protocol. |
| `layout/projector.py` | `LinearProjector` / `PolarProjector`. **The band-space abstraction.** |
| `scene/marks.py` | `Scene`, `Layer`, `Paint`, `TextStyle`, all mark types, `Path` with centre-parameterised arcs. |
| `style/color.py` | `Color`, `parse_color`. |
| `style/theme.py` | `Theme`, `NodeStyle`, `resolve()`. |
| `text/metrics.py` | `TextMetrics` protocol, `FallbackMetrics` (Qt-free), `CachedMetrics`. |
| `tracks/base.py` | `Track` ABC, `TrackData`, `TrackContext`, `Legend`, `register()`. |
| `ops/command.py` | `Command`, `CommandStack`. |
| `doc/document.py` | `Document`, project file layout. |
| `annot/table.py` | `AnnotationTable` and the `.mytrack` grammar. |

### 2.1 The central invariant

Every layout is **two independent coordinate assignments**:

- a **cross** coordinate — `y` in linear modes, `angle` in polar modes — derived only from
  the left-to-right order of visible tips;
- an **along** coordinate — `x` in linear modes, `radius` in polar — derived only from
  branch length or topological depth.

Reordering children (ladderize, rotate) changes only the cross coordinate. Rescaling or
switching phylogram/cladogram changes only the along coordinate. Keep them separable.

### 2.2 Band space — why tracks are layout-agnostic

Tracks never compute scene coordinates. They work in `(row, offset)`:

- `row` — continuous tip-row coordinate; visible tip *i* occupies `[i, i+1]`, centre `i+0.5`.
  A collapsed clade simply occupies more rows, so tracks need no special case for it.
- `offset` — distance outward from the track baseline (past the tip labels), growing away
  from the tree.

`Projector.point/cell/rect/tangential/outward/text` map band space into the scene. In a
linear layout a cell is a rectangle; in a polar layout the identical call yields an annular
sector. **A track written against the projector works in all four rooted layout modes with
no conditionals.** Use `projector.rect()` (returns `None` in polar) to take the batched
`RectsMark` fast path when available, and fall back to `projector.cell()` otherwise.

### 2.3 Performance rules

A 100k-leaf tree is ~200k nodes and ~400k segments.

- Never create one scene object per node. Group by paint and emit `LinesMark` / `RectsMark`
  batches.
- Never recurse over the tree.
- Layouts write into `LayoutFrame`'s flat arrays via `set_xy` / `set_polar` / `set_rows` /
  `add_segment` / `add_arc`.
- Measure labels through `CachedMetrics`, never per frame.

---

## 3. Module map and ownership

Files marked **[frozen]** already exist. Everything else is to be written.

```
src/makeyourtree/
  core/        node.py tree.py traversal.py diagnostics.py errors.py     [frozen]
  io/          __init__.py detect.py newick.py nexus.py phyloxml.py nhx.py writer.py
  layout/      params.py frame.py projector.py                           [frozen]
               __init__.py linear.py polar.py unrooted.py collapse.py scalebar.py
  ops/         command.py                                                [frozen]
               rooting.py order.py edit.py select.py
  style/       color.py theme.py                                         [frozen]
               palettes.py scales.py
  tracks/      base.py                                                   [frozen]
               shapes.py ranges.py strip.py binary.py gradient.py heatmap.py
               bars.py boxplot.py pie.py domains.py text.py symbols.py
               line.py connections.py
  scene/       marks.py                                                  [frozen]
               compose.py legend.py
  render/      svg.py backend.py
  doc/         document.py                                               [frozen]
               io.py
  annot/       table.py                                                  [frozen]
               parser.py loaders.py
  text/        metrics.py                                                [frozen]
  cli.py
src/makeyourtree_studio/
  app.py main_window.py actions.py settings.py
  canvas/      view.py layers.py qt_backend.py qt_metrics.py interaction.py
  panels/      tree_panel.py style_panel.py tracks_panel.py search_panel.py inspector.py
  dialogs/     export_dialog.py import_dialog.py about_dialog.py
  export/      raster.py
  packaging/   makeyourtree.spec
tests/
```

---

## 4. Formats

### 4.1 Annotation table `.mytrack`
Specified in full in `src/makeyourtree/annot/table.py`. Sectioned INI-style:
`[track]`, `[options]`, `[columns]`, `[colors]`, `[legend]`, `[data]`. Separator in
`[data]` is auto-detected: tab, else comma, else runs of 2+ spaces. Empty or `-` means
**no value** — render a gap, never a zero.

### 4.2 Project `.mytree`
ZIP container: `project.json` (manifest), `tree.nwk`, `tracks/<id>.json`, `assets/<name>`.
Flat variant `.mytree.json` inlines the tree and tracks. Unknown manifest keys round-trip
through `Document.unknown` — never silently drop a field written by a newer build.

---

## 5. Conventions

- SPDX header on every file, first line:
  - core (`src/makeyourtree/`): `# SPDX-License-Identifier: MIT`
  - studio (`src/makeyourtree_studio/`): `# SPDX-License-Identifier: MIT`
- Type hints everywhere; `from __future__ import annotations` at the top.
- Docstrings explain **why**, not what. State the algorithm and cite its source.
- No `print`; diagnostics go to a `DiagnosticSink`, real failures raise from
  `core/errors.py`.
- Public API is re-exported from each subpackage's `__init__.py`.
- Tests: `pytest`, headless. Qt tests set `QT_QPA_PLATFORM=offscreen`.
- Comments match the surrounding density. No banner comments, no commented-out code.

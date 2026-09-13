# Project status

**Last updated:** 2026-09-13 · **Suite:** 2286 passing, 0 failing (~43 s)
**Read `docs/SPEC.md` first** — it has the architecture and the frozen contracts. This
file is the handoff note: what actually works, what is thin, and what to do next.

Be honest when you edit this. A known gap is useful; a false claim is not.

---

## 1. What is built

**Core library (`src/makeyourtree/`, MIT, no Qt) — solid.**

- **Input:** Newick with the full quoting/nested-comment grammar, NHX, BEAST/FigTree
  `[&k=v]` metacomments, NEXUS with `TRANSLATE` blocks and rooting hints, phyloXML with
  entity expansion disabled (XXE and billion-laughs both refused). Parsing is lenient:
  problems become diagnostics, not exceptions. A 100k-leaf tree parses in ~2.5 s.
- **Layouts:** rectangular, slanted, circular, radial, unrooted (Felsenstein equal-angle
  and equal-daylight). Unrooted output preserves every branch length exactly and is planar
  by construction — both are asserted on random trees.
- **Operations:** reroot on edge, midpoint, outgroup, unroot, ladderize, rotate, collapse,
  prune, extract subtree — all undoable. A 20-step scripted session round-trips to
  byte-identical Newick.
- **Tracks:** 13 registered types (clade range, colour strip, binary matrix, gradient,
  heatmap, bar, box plot, pie, domain architecture, text, symbols, line, connections). All
  work in every rooted layout mode via band space.
- **Output:** pure-Python SVG writer, plus PNG and vector PDF through Qt in the studio.
- **CLI:** `info`, `convert`, `render`, `reroot`, `guide`, `plan`. `render` writes SVG, PDF and PNG
  with `--dpi` and physical page sizes (`--width 180mm`, `--page a4`). PNG and PDF
  come from an entry point the studio registers, so the MIT core still imports no Qt.

- **Guided help:** a branching interview (`makeyourtree guide`, or Help ▸ Guide Me)
  produces a saveable, resumable `.myplan` of concrete steps with runnable commands.
  `--from-figure` measures a published PDF or image — radial ink distribution, colour
  saturation, hue count — and pre-fills what it can evidence, stating confidence. It
  measures rather than recognises; there is no model and no network call.

**Studio (`src/makeyourtree_studio/`, MIT, PySide6) — works, unfinished at the edges.**

- Canvas with layer-batched painting (a 5000-leaf, 9999-node tree produces **4** graphics
  items, not one per node), anchored wheel zoom that never relayouts, panning, rubber-band
  selection, `LayoutFrame`-based hit-testing, tooltips, context menu.
- Panels: tree, style, tracks, search, inspector. Every edit flows through `Session.do()`,
  so nothing bypasses undo; slider drags coalesce into one history entry.
- Dialogs: export (with live pixel-dimension prediction), annotation import wizard with a
  match report, about, third-party licences.
- Project save/load (`.mytree`), settings persistence, command palette, editable shortcuts.

**Verified by running it, not just by tests.** `tools/smoke_studio.py` drives the real Qt
platform through 22 steps and writes `docs/screenshots/`. Figure quality is good: track
cell centres equal tip y *exactly* (checked numerically, not by eye), circular fans keep
tangential captions upright, legends carry correct swatches and gradient ramps, collapsed
clades leave their rows blank, dark theme repaints correctly.

---

## 2. What is thin — read before promising anything

| Area | Reality |
|---|---|
| **Packaging** | **Built and launched on Windows, 2026-09-04.** `build.py` passes 13/13 checks and the bundle opens a real window with a tree loaded from the command line. Doing so exposed a fatal bug: the spec used `app.py` as the entry script, so PyInstaller ran it as `__main__`, its relative imports failed, and the windowed build died with a bare exit status 1. Fixed by `packaging/launcher.py`. **macOS and Linux remain unbuilt.** |
| **Large trees** | Fine to a few thousand tips. Layout switching costs ~6 s (circular) to ~9 s (unrooted) at 5000 tips **with no progress indication** — the window is unresponsive, though not hung. |
| **Font metrics under Qt** | The whole suite runs fontless, so `QtMetrics`' real Qt path — which decides whether reserved label widths match painted ones — is covered by structure only. `tools/smoke_studio.py` is currently the sole evidence it works with real fonts. |
| **Tracks in unrooted mode** | They draw as a column beside the bounding box, in tip order, **aligned to nothing**. The core emits `compose.approximate-band-space`; the app surfaces it only as a count. Misleading by default — needs a product decision, not just a fix. |
| **Visual identity** | No icons (text-only toolbar). Application chrome is not themed, so dark mode gives a dark figure inside light menus. |
| **Project persistence** | Correct now, but had never been exercised end-to-end before 2026-08-20 — a live metrics object in `document.metadata` made every save crash. Regression tests added. |
| **Python version** | Settled 2026-09-04: `>=3.12` everywhere. 3.12 is the only version MakeYourTree has ever been tested on, so it is the only one claimed. 3.11 may well work; nobody has run the suite there. |
| **Untested seams** | `contextMenuEvent`'s `exec()`, and the modal file/message dialogs. |
| **Circular figure furniture** | Fixed 2026-09-13 (MS-13): a fan's header row is now bounded by the wedge its arc leaves open, and its scale bar is placed below the drawing. What remains is a *limit*, not a bug — a narrow gap cannot hold many long captions, so some are dropped. They are reported, and the legend still names every track, but a user who wants them all has to widen the arc. |

---

## 3. Suggested next steps

**See `docs/ERROR-REPORT.md` first** — a verified list of open bugs, manuscript
errors and their fixes, written 2026-09-05 by running everything. It supersedes the
ordering below where the two disagree.

Roughly in value order.

1. **Build on macOS and Linux.** Windows is done and verified; the other two are still
   unproven, and PyInstaller cannot cross-build. Confirm the licence files land inside the
   bundle and that Qt ships as separate, replaceable shared libraries — that last one is an
   LGPL obligation (§4(d)(1)) and should be tested, not assumed. Note that `verify_bundle`
   cannot tell you the app *runs*; launch it, as the Windows entry-script bug showed.
2. **Decide what unrooted mode does with tracks.** Options: hide them with a clear message,
   draw them honestly as an unaligned column with a visible caption, or offer a
   tip-ordered ring. Currently it is the middle option without the caption.
3. **Make layout switching non-blocking** on large trees, or at least show progress.
4. **Icons and themed chrome.** Use only permissively licensed sets (Lucide/Tabler/Feather
   MIT, Material Symbols Apache-2.0) and record each in `THIRD-PARTY-NOTICES.md` **before
   committing the asset**.
5. Profile the remaining large-tree paths; the quadratic `select()` bug that froze the UI
   for 150 s was likely not the only one of its class.
6. Consider whether a fan should reserve the header room it needs. Today the arc is
   taken literally and captions that do not fit the gap are dropped with a message.
   Growing the gap on demand would caption everything, but it would also silently
   change a layout the user asked for; that is a product decision, not a bug fix.

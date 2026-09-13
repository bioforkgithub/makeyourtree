# MakeYourTree Studio — implementation specification

The desktop application. PySide6/Qt6, **MIT** (as is the rest of MakeYourTree).
Read `docs/SPEC.md` first — the core contracts it describes are unchanged and frozen.

## 0. Licence rules — enforced by `tests/test_licensing.py`

1. Every file under `src/makeyourtree_studio/` starts with
   `# SPDX-License-Identifier: MIT`.
2. **Never import `QtCharts`, `QtDataVisualization` or `QtVirtualKeyboard`.** They are
   GPL-3.0-only in the open-source Qt edition and would force the whole product to GPL.
   Charts come from our own `makeyourtree.tracks` renderers.
3. Never add Qt imports to `src/makeyourtree/`. The core stays toolkit-free.
4. No third-party product branding anywhere in source.

## 1. Frozen studio contracts — already written, do not change

| File | What it fixes |
|---|---|
| `session.py` | `Session` (QObject) — the open document, undo stack, selection, and every change signal. `Dirty` — how much of the pipeline went stale. **All tree edits go through `Session.do()`**; nothing calls `command.apply()` directly. |
| `actions.py` | `ActionSpec`, `ActionRegistry`, `Group`. Every command is declared once here; menus, toolbars, context menus, the command palette and the shortcut editor are all views of this registry. |

`Session` signals: `documentReplaced`, `dirtied(int)`, `recomposed`, `selectionChanged`,
`historyChanged`, `diagnosticsChanged`, `tracksChanged`, `modifiedChanged(bool)`,
`statusMessage(str, int)`.

Recomposition is staged via `Dirty`: `OVERLAY` (selection only) → `STYLE` → `ORDER` →
`LAYOUT` → `TOPOLOGY`. Panels call `session.invalidate(level)`; the canvas coalesces on a
zero-timer and calls `session.recompose()` once.

## 2. Class names each unit must expose

These are load-bearing across units. Match them exactly.

```python
# canvas/view.py
class TreeCanvas(QGraphicsView):
    def __init__(self, session: Session, parent=None) -> None: ...
    def fit_to_view(self) -> None: ...
    def zoom_by(self, factor: float, anchor=None) -> None: ...
    def reset_zoom(self) -> None: ...
    def center_on_node(self, node_id: int) -> None: ...
    def export_image(self, path: str, *, scale: float = 2.0) -> None: ...

# canvas/qt_backend.py
class QtBackend:            # implements makeyourtree.render.backend.RenderBackend
    def __init__(self, painter: QPainter) -> None: ...

# canvas/qt_metrics.py
class QtMetrics:            # implements makeyourtree.text.metrics.TextMetrics
    def __init__(self, family: str | None = None) -> None: ...

# panels/*.py   — each is a QWidget taking the session
class TreePanel(QWidget):      def __init__(self, session: Session, parent=None): ...
class StylePanel(QWidget):     def __init__(self, session: Session, parent=None): ...
class TracksPanel(QWidget):    def __init__(self, session: Session, parent=None): ...
class SearchPanel(QWidget):    def __init__(self, session: Session, parent=None): ...
class InspectorPanel(QWidget): def __init__(self, session: Session, parent=None): ...

# dialogs/*.py
class ExportDialog(QDialog):   def __init__(self, session: Session, parent=None): ...
class ImportDialog(QDialog):   def __init__(self, session: Session, parent=None): ...
class AboutDialog(QDialog):    def __init__(self, parent=None): ...
class LicensesDialog(QDialog): def __init__(self, parent=None): ...

# export/raster.py
def export_png(scene, path, *, scale=2.0, background=None) -> None: ...
def export_pdf(scene, path, *, size=None) -> None: ...
def export_svg(scene, path) -> None: ...     # delegates to makeyourtree.render.render_svg
```

## 3. Performance — the rule that decides the canvas design

A 100 000-leaf tree is ~200 000 nodes and ~400 000 segments. `QGraphicsScene` degrades
badly past ~50 000 items.

- **Never one `QGraphicsItem` per node.** Use a small fixed number of layer items
  (one per `makeyourtree.scene.Layer`), each painting thousands of primitives in its `paint()`.
- `scene.setItemIndexMethod(QGraphicsScene.NoIndex)` — with a handful of huge items the BSP
  index is pure overhead.
- `boundingRect()` returns a cached rect and never computes; wrap changes in
  `prepareGeometryChange()`.
- Batch with `QPainter.drawLines(...)` grouped by pen, built from a culled selection.
- Cosmetic pens so stroke width stays constant under zoom.
- Zoom must **never** trigger a relayout — it is a view transform only.
- Hit-testing goes through `LayoutFrame.hit()`, not Qt item picking.

## 4. Window layout

Central `TreeCanvas`. Dockable panels: **Tree** (left), **Style**, **Tracks**,
**Search**, **Inspector** (right, tabbed). Menu bar from `Group.ORDER`. Toolbar with
layout mode, branch mode, zoom, ladderize, align tips. Status bar showing the diagnostic
count and the current selection.

## 5. Keyboard

`Ctrl+O` open · `Ctrl+S` save · `Ctrl+Shift+S` save as · `Ctrl+E` export ·
`Ctrl+Z` / `Ctrl+Shift+Z` undo/redo · `Ctrl+F` search · `Ctrl+0` fit ·
`Ctrl+=` / `Ctrl+-` zoom · `Ctrl+P` command palette ·
`R` reroot on selection · `M` midpoint root · `L` ladderize · `C` collapse/expand ·
`Delete` prune selection · `Esc` clear selection.

No two actions may share a sequence — `ActionRegistry.conflicts()` must return empty,
and a test asserts it.

## 6. Third-party licences at runtime — a licence obligation

`Help ▸ Third-Party Licences` must open `LicensesDialog`, showing the contents of
`THIRD-PARTY-NOTICES.md` and the full texts in `LICENSES/`. `AboutDialog` must show the
exact Qt version, so a user can build a compatible replacement.

This satisfies LGPL-3.0 §4(a) and §4(c). It is not optional and it is not decoration.
Locate the files relative to the package, and make it work both from a source checkout and
from a PyInstaller bundle (`sys._MEIPASS`).

## 7. Testing

`QT_QPA_PLATFORM=offscreen` (already forced by `tests/conftest.py`). Note that the
offscreen platform reports **zero font families**, so assert on geometry and structure,
never on rasterised glyph pixels.

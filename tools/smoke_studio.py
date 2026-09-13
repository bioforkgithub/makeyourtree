# SPDX-License-Identifier: MIT
"""Manual end-to-end smoke run of MakeYourTree Studio on the real Qt platform.

Not part of the test suite: it needs a real windowing system and real fonts,
and it writes screenshots into ``docs/screenshots/``.  Run it with

    .venv/Scripts/python.exe tools/smoke_studio.py

Every step prints PASS/FAIL so a failure is attributable to one operation.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402

from makeyourtree.annot.loaders import load_annotation  # noqa: E402
from makeyourtree.layout.params import LayoutMode  # noqa: E402

from makeyourtree_studio.app import build_application  # noqa: E402
from makeyourtree_studio.export.raster import (export_pdf, export_png,  # noqa: E402
                                           export_svg)
from makeyourtree_studio.settings import Settings  # noqa: E402

SHOTS = ROOT / "docs" / "screenshots"
OUT = ROOT / "build" / "smoke"
FAILURES: list[str] = []


def step(name):
    def wrap(fn):
        def run(*a, **kw):
            try:
                value = fn(*a, **kw)
            except Exception:
                FAILURES.append(name)
                print("FAIL  " + name)
                traceback.print_exc()
                return None
            extra = ("  -- " + value) if isinstance(value, str) else ""
            print("PASS  " + name + extra)
            return value
        return run
    return wrap


def pump(app, rounds=6):
    for _ in range(rounds):
        app.processEvents()


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope,
                          str(OUT / "settings"))

    settings = Settings.for_file(OUT / "smoke.ini")
    app, window = build_application(["smoke"], settings)
    window.resize(1600, 1000)
    window.show()
    pump(app, 12)
    print("INFO  platform=" + repr(app.platformName()))
    print("INFO  font families available: %d" % len(QFontDatabase.families()))

    @step("open examples/primates.nwk")
    def open_tree():
        assert window.open_path(ROOT / "examples" / "primates.nwk")
        return "%d tips" % len(window.session.tree.leaves)
    open_tree()
    pump(app)

    @step("attach both example .mytrack tracks")
    def add_tracks():
        names = []
        for mytrack in ("primates_region.mytrack", "primates_bodymass.mytrack"):
            track = load_annotation(ROOT / "examples" / mytrack,
                                    window.session.tree)
            window.session.add_track(track)
            names.append(track.id)
        return ", ".join(names)
    add_tracks()
    pump(app)

    for mode in LayoutMode:
        @step("render + screenshot " + mode.value)
        def render(mode=mode):
            window.set_layout_mode(mode)
            pump(app, 10)
            window.canvas.fit_to_view()
            pump(app, 10)
            pix = window.grab()
            path = SHOTS / ("studio-" + mode.value + ".png")
            assert pix.save(str(path)), "QPixmap.save failed"
            layers = sorted(k.name for k in window.canvas.layer_items())
            return "%s %dx%d layers=%s" % (path.name, pix.width(),
                                           pix.height(), layers)
        render()

    @step("back to rectangular")
    def back():
        window.set_layout_mode(LayoutMode.RECTANGULAR)
        pump(app, 8)
        return window.session.params.mode.value
    back()

    @step("search finds Homo")
    def search():
        panel = window.search_panel
        panel.query_edit.setText("Homo")
        pump(app)
        hits = panel.hits
        assert hits, "no hits for 'Homo'"
        return "%d hits, session=%d" % (len(hits),
                                        len(window.session.search_hits))
    search()

    @step("collapse a clade, then expand all")
    def collapse():
        tree = window.session.tree
        internal = [n for n in tree.nodes
                    if not n.is_leaf and n.parent is not None]
        target = internal[len(internal) // 2]
        window.session.set_selection([target.id])
        pump(app)
        before = len(window.session.tree.collapsed_nodes())
        window.actions_registry.action("tree.collapse").trigger()
        pump(app, 6)
        after = len(window.session.tree.collapsed_nodes())
        assert after != before, "collapse did nothing"
        window.canvas.fit_to_view()
        pump(app, 6)
        window.grab().save(str(SHOTS / "studio-collapsed.png"))
        window.expand_all()
        pump(app, 6)
        assert len(window.session.tree.collapsed_nodes()) == 0
        return "collapsed %d->%d->0" % (before, after)
    collapse()

    @step("midpoint root")
    def midpoint():
        window.midpoint_root()
        pump(app, 6)
        return "rooted"
    midpoint()

    @step("undo / redo round trip")
    def undo_redo():
        from makeyourtree.io import write_newick
        after_edit = write_newick(window.session.tree)
        window.session.undo()
        pump(app, 6)
        undone = write_newick(window.session.tree)
        assert undone != after_edit, "undo changed nothing"
        window.session.redo()
        pump(app, 6)
        redone = write_newick(window.session.tree)
        assert redone == after_edit, "redo did not restore the edit"
        window.session.undo()
        pump(app, 6)
        return "undo/redo consistent"
    undo_redo()

    @step("track visibility toggle")
    def toggle_track():
        track = window.session.document.tracks[0]
        window.session.set_track_visible(track.id, False)
        pump(app, 8)
        hidden = window.session.scene
        window.session.set_track_visible(track.id, True)
        pump(app, 8)
        shown = window.session.scene
        assert hidden is not None and shown is not None
        return track.id + " hidden/shown ok"
    toggle_track()

    @step("panels show real content")
    def panels():
        tp = window.tree_panel
        root_index = tp.model.index(0, 0)
        rows = tp.model.rowCount(root_index)
        tracks = window.tracks_panel.model.rowCount()
        return "root children=%d tracks listed=%d" % (rows, tracks)
    panels()

    @step("export SVG / PNG / PDF")
    def exports():
        scene = window.session.recompose(force=True)
        assert scene is not None
        svg, png, pdf = OUT / "figure.svg", OUT / "figure.png", OUT / "figure.pdf"
        export_svg(scene, svg)
        export_png(scene, png, scale=2.0)
        export_pdf(scene, pdf)
        text = svg.read_text(encoding="utf-8")
        assert text.lstrip().startswith("<?xml") or text.lstrip().startswith("<svg")
        assert "</svg>" in text and svg.stat().st_size > 5000, "SVG too small"
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert png.stat().st_size > 10000, "PNG too small"
        raw = pdf.read_bytes()
        assert raw[:5] == b"%PDF-" and b"%%EOF" in raw and len(raw) > 3000
        return "svg=%dB png=%dB pdf=%dB" % (svg.stat().st_size,
                                            png.stat().st_size, len(raw))
    exports()

    @step("full-window screenshot with panels")
    def final_shot():
        window.set_layout_mode(LayoutMode.RECTANGULAR)
        window.canvas.fit_to_view()
        pump(app, 10)
        window.grab().save(str(SHOTS / "studio-window.png"))
        window.canvas.grab().save(str(SHOTS / "studio-canvas.png"))
        return "studio-window.png, studio-canvas.png"
    final_shot()

    @step("dark theme repaints")
    def dark():
        w_before = window.session.theme.background
        window.set_theme_name("dark")
        pump(app, 10)
        window.canvas.fit_to_view()
        pump(app, 10)
        window.grab().save(str(SHOTS / "studio-dark.png"))
        after = window.session.theme.background
        assert after != w_before, "theme did not change"
        assert window.style_panel.theme_combo.currentData() == "dark"
        window.set_theme_name("light")
        pump(app, 10)
        return "dark screenshot written"
    dark()

    @step("align tips + guide lines, rectangular and circular")
    def guides():
        window.session.set_params(align_tips=True, guide_lines=True)
        for mode in (LayoutMode.RECTANGULAR, LayoutMode.CIRCULAR):
            window.set_layout_mode(mode)
            pump(app, 8)
            window.canvas.fit_to_view()
            pump(app, 8)
            window.grab().save(str(SHOTS / ("studio-guides-" + mode.value + ".png")))
        window.session.set_params(align_tips=False)
        window.set_layout_mode(LayoutMode.RECTANGULAR)
        pump(app, 8)
        return "two guide screenshots"
    guides()

    @step("save project, reopen, settings survive")
    def project():
        window.session.set_params(row_spacing=22.0)
        pump(app, 4)
        path = OUT / "smoke.mytree"
        assert window.save_to(path)
        window.open_path(path)
        pump(app, 8)
        assert abs(window.session.params.row_spacing - 22.0) < 1e-9
        assert len(window.session.document.tracks) == 2
        window.session.set_params(row_spacing=16.0)
        pump(app, 4)
        return "%d tracks, spacing restored" % len(window.session.document.tracks)
    project()

    @step("export dialog produces a file")
    def export_dialog():
        from makeyourtree_studio.dialogs.export_dialog import ExportDialog
        dlg = ExportDialog(window.session, window)
        target = OUT / "dialog.png"
        dlg._path.setText(str(target))
        dlg.run_export()
        dlg.wait_for_export(20000)
        pump(app, 6)
        assert target.exists() and target.stat().st_size > 5000, "no file"
        dlg.close()
        return "%s %dB" % (target.name, target.stat().st_size)
    export_dialog()

    @step("bigger tree: bacteria + heatmap + strip")
    def bacteria():
        assert window.open_path(ROOT / "examples" / "bacteria.nwk")
        for mytrack in ("bacteria_expression.mytrack", "bacteria_resistance.mytrack"):
            window.session.add_track(
                load_annotation(ROOT / "examples" / mytrack, window.session.tree))
        pump(app, 8)
        window.canvas.fit_to_view()
        pump(app, 10)
        window.grab().save(str(SHOTS / "studio-bacteria.png"))
        window.canvas.grab().save(str(SHOTS / "studio-bacteria-canvas.png"))
        scene = window.session.recompose(force=True)
        export_png(scene, OUT / "bacteria.png", scale=2.0)
        return "%d tips, scene %.0fx%.0f" % (window.session.tree.n_leaves,
                                             scene.width, scene.height)
    bacteria()

    @step("quit cleanly")
    def quit_():
        window.close()
        pump(app, 6)
        return "closed"
    quit_()

    print()
    if FAILURES:
        print("%d FAILED: %s" % (len(FAILURES), FAILURES))
        return 1
    print("all smoke steps passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

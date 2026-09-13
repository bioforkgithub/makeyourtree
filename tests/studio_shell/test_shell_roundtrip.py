# SPDX-License-Identifier: MIT
"""Two round trips the product has to survive without losing the user's work.

*Undo.* A scripted twenty-step editing session must undo back to a byte-identical
Newick string. Anything less means a command captured too little state to
reverse itself, and the user's tree quietly drifts every time they experiment.

*Save and reopen.* A project must come back with its layout parameters, its
track order and its collapsed clades intact. These three are the state most
easily lost, because none of them lives in the tree.
"""

from __future__ import annotations

from pathlib import Path

from shell_helpers import ScriptedWindow, close_window, make_window, trigger

from makeyourtree.layout.params import BranchMode, CollapseShape, LayoutMode
from makeyourtree.tracks.base import get_track_class

TRACK_TYPES = ("color-strip", "binary-matrix", "text-labels")


def _script(window: ScriptedWindow) -> list[str]:
    """Twenty edits, each of which is guaranteed to push exactly one command.

    Deliberately mixed: ordering, rooting, collapsing and pruning exercise the
    four different undo strategies in ``makeyourtree.ops``.
    """
    tree = window.session.tree
    ab = tree.by_name("ab").id
    gd = tree.by_name("gd").id
    ez = tree.by_name("ez").id
    eta = tree.by_name("eta").id
    beta = tree.by_name("beta").id
    steps: list[str] = []

    def edit(action_id: str, selection: list[int] | None = None) -> None:
        if selection is not None:
            window.session.set_selection(selection)
        trigger(window, action_id)
        steps.append(action_id)

    edit("tree.order.ladderize_asc")
    edit("tree.order.ladderize_desc")
    edit("tree.order.rotate", [tree.root.id])
    edit("tree.collapse", [ab])
    edit("tree.collapse", [ab])
    edit("tree.root.midpoint")
    edit("tree.order.ladderize_asc")
    edit("tree.root.reroot", [gd])
    edit("tree.order.rotate", [gd])
    edit("tree.collapse", [ez])
    edit("tree.prune", [beta])
    edit("tree.order.ladderize_desc")
    edit("tree.root.reroot", [eta])
    edit("tree.order.rotate", [tree.root.id])
    edit("tree.order.ladderize_asc")
    edit("tree.root.midpoint")
    edit("tree.collapse", [gd])
    edit("tree.order.ladderize_desc")
    edit("tree.order.rotate", [gd])
    edit("tree.order.ladderize_asc")
    return steps


def test_a_scripted_twenty_step_session_undoes_exactly(loaded: ScriptedWindow):
    original = loaded.session.tree.to_newick()
    steps = _script(loaded)

    assert len(steps) == 20
    assert len(loaded.session.stack.history()) == 20, (
        "every scripted step must produce one undoable command")
    assert loaded.session.tree.to_newick() != original
    assert loaded.session.is_modified

    for _ in range(20):
        loaded.session.undo()

    assert loaded.session.tree.to_newick() == original
    assert not loaded.session.stack.can_undo
    assert not loaded.session.is_modified


def test_redoing_the_whole_script_reproduces_the_edited_tree(
        loaded: ScriptedWindow):
    original = loaded.session.tree.to_newick()
    _script(loaded)
    edited = loaded.session.tree.to_newick()
    for _ in range(20):
        loaded.session.undo()
    assert loaded.session.tree.to_newick() == original
    for _ in range(20):
        loaded.session.redo()
    assert loaded.session.tree.to_newick() == edited
    for _ in range(20):
        loaded.session.undo()
    assert loaded.session.tree.to_newick() == original


def test_the_menu_items_follow_the_history(loaded: ScriptedWindow):
    undo = loaded.actions_registry.action("edit.undo")
    redo = loaded.actions_registry.action("edit.redo")
    assert not undo.isEnabled() and not redo.isEnabled()
    _script(loaded)
    assert undo.isEnabled() and not redo.isEnabled()
    for _ in range(20):
        trigger(loaded, "edit.undo")
    assert not undo.isEnabled() and redo.isEnabled()
    for _ in range(20):
        trigger(loaded, "edit.redo")
    assert undo.isEnabled() and not redo.isEnabled()


def test_the_canvas_survives_the_whole_script(loaded: ScriptedWindow):
    from makeyourtree.scene.marks import Layer

    _script(loaded)
    loaded.canvas.refresh()
    assert Layer.BRANCHES in loaded.canvas.layer_items()
    for _ in range(20):
        loaded.session.undo()
    loaded.canvas.refresh()
    assert Layer.BRANCHES in loaded.canvas.layer_items()


# ------------------------------------------------------------ save / reopen


def _prepare_project(window: ScriptedWindow) -> dict:
    """Set every piece of state a project has to carry, and describe it."""
    window.session.set_params(mode=LayoutMode.CIRCULAR,
                              branch_mode=BranchMode.CLADOGRAM_LEVEL,
                              align_tips=True,
                              row_spacing=23.5,
                              collapse_shape=CollapseShape.TRAPEZOID)
    for type_id in TRACK_TYPES:
        track = window.tracks_panel.add_track_of_type(type_id)
        assert track is not None, f"{type_id} should be a registered track type"
    window.session.move_track(window.session.document.tracks[0].id, 2)

    collapsed = [window.session.tree.by_name("gd").id,
                 window.session.tree.by_name("ez").id]
    window.session.set_selection(collapsed)
    trigger(window, "tree.collapse")

    return {
        "mode": window.session.params.mode,
        "branch_mode": window.session.params.branch_mode,
        "align_tips": window.session.params.align_tips,
        "row_spacing": window.session.params.row_spacing,
        "collapse_shape": window.session.params.collapse_shape,
        "track_ids": [t.id for t in window.session.document.tracks],
        "track_types": [t.type_id for t in window.session.document.tracks],
        "collapsed": sorted(n.id for n in window.session.tree.collapsed_nodes()),
        "newick": window.session.tree.to_newick(),
    }


def test_a_project_survives_save_close_and_reopen(qapp, tmp_path: Path,
                                                  newick_file: Path):
    first = make_window(tmp_path)
    assert first.open_path(newick_file)
    expected = _prepare_project(first)
    target = tmp_path / "restored.mytree"
    assert first.save_to(target)
    assert not first.session.is_modified
    close_window(first)

    second = make_window(tmp_path)
    try:
        assert second.open_path(target)
        params = second.session.params
        assert params.mode is expected["mode"]
        assert params.branch_mode is expected["branch_mode"]
        assert params.align_tips is expected["align_tips"]
        assert params.row_spacing == expected["row_spacing"]
        assert params.collapse_shape is expected["collapse_shape"]

        tracks = second.session.document.tracks
        assert [t.id for t in tracks] == expected["track_ids"]
        assert [t.type_id for t in tracks] == expected["track_types"]

        assert sorted(n.id for n in second.session.tree.collapsed_nodes()) == \
            expected["collapsed"]
        assert second.session.tree.to_newick() == expected["newick"]

        # The reopened document is what the menus report, not just what is on
        # disk: a check mark that disagrees with the document is a bug.
        assert second.actions_registry.action("view.mode.circular").isChecked()
        assert second.actions_registry.action(
            "view.branch.cladogram_level").isChecked()
        assert second.actions_registry.action("view.align_tips").isChecked()
        assert not second.session.is_modified
    finally:
        close_window(second)


def test_a_flat_project_round_trips_too(qapp, tmp_path: Path,
                                        newick_file: Path):
    """The single-file ``.mytree.json`` variant carries the same state."""
    first = make_window(tmp_path)
    assert first.open_path(newick_file)
    expected = _prepare_project(first)
    target = tmp_path / "flat.mytree.json"
    assert first.save_to(target)
    assert target.read_text(encoding="utf-8").lstrip().startswith("{")
    close_window(first)

    second = make_window(tmp_path)
    try:
        assert second.open_path(target)
        assert second.session.params.mode is expected["mode"]
        assert [t.id for t in second.session.document.tracks] == \
            expected["track_ids"]
        assert sorted(n.id for n in second.session.tree.collapsed_nodes()) == \
            expected["collapsed"]
    finally:
        close_window(second)


def test_the_track_types_used_by_the_round_trip_exist():
    for type_id in TRACK_TYPES:
        assert get_track_class(type_id) is not None

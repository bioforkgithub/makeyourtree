# SPDX-License-Identifier: MIT
"""The palette is how a user reaches the commands that have no shortcut.

Its whole value is that a partial, misremembered query finds the right command,
so the tests are about ranking, not about the widget: the assertions say which
command comes *first*, not merely that it appears somewhere in the list.
"""

from __future__ import annotations

import pytest

from makeyourtree_studio.actions import ActionRegistry
from makeyourtree_studio.command_palette import (CommandPalette, fuzzy_score,
                                             rank_specs)
from makeyourtree_studio.main_window import declare_actions


@pytest.fixture
def registry() -> ActionRegistry:
    r = ActionRegistry()
    declare_actions(r)
    return r


# ------------------------------------------------------------------ matching


def test_a_subsequence_matches_and_a_missing_letter_does_not():
    assert fuzzy_score("ldz", "Ladderize Ascending") is not None
    assert fuzzy_score("zzz", "Ladderize Ascending") is None


def test_the_empty_query_matches_everything(registry: ActionRegistry):
    assert len(rank_specs(registry.specs(), "")) == len(registry.specs())


def test_matching_at_a_word_boundary_beats_matching_inside_a_word():
    boundary = fuzzy_score("mr", "Midpoint Root")
    inside = fuzzy_score("mr", "Command Palette Ordinary")
    assert boundary is not None and inside is not None
    assert boundary > inside


def test_a_shorter_name_wins_a_tie():
    assert fuzzy_score("ab", "Ab") > fuzzy_score("ab", "Ab Cdefghijklmnop")


@pytest.mark.parametrize("query,expected", [
    ("midpoint", "tree.root.midpoint"),
    ("third", "help.licenses"),
    ("export", "file.export"),
    ("dark", "view.theme"),
    ("ladderize asc", "tree.order.ladderize_asc"),
    ("import annot", "annotate.import"),
    ("mode.circular", "view.mode.circular"),
    ("fit", "view.zoom_fit"),
])
def test_a_partial_query_puts_the_right_command_first(registry: ActionRegistry,
                                                      query: str,
                                                      expected: str):
    ranked = rank_specs(registry.specs(), query)
    assert ranked, f"{query!r} matched nothing"
    assert ranked[0].spec.id == expected


def test_the_action_id_is_searchable_but_ranks_below_the_name(
        registry: ActionRegistry):
    by_id = rank_specs(registry.specs(), "tree.root.unroot")
    assert by_id[0].spec.id == "tree.root.unroot"


# -------------------------------------------------------------------- widget


def test_the_palette_lists_every_command_when_empty(qapp,
                                                    registry: ActionRegistry):
    palette = CommandPalette(registry)
    try:
        assert len(palette.matches()) == len(registry.specs())
        assert palette.list.columnCount() == 3
    finally:
        palette.close()


def test_the_palette_filters_as_you_type(qapp, registry: ActionRegistry):
    palette = CommandPalette(registry)
    try:
        palette.query_edit.setText("zoom")
        ids = palette.match_ids()
        assert ids, "typing a real word must not empty the list"
        assert all(i.startswith("view.zoom") for i in ids[:3])
        assert len(ids) < len(registry.specs())

        palette.query_edit.setText("qqqqzzzz")
        assert palette.match_ids() == []
        assert "No matching" in palette.status_label.text()
    finally:
        palette.close()


def test_each_row_shows_the_group_and_the_shortcut(qapp,
                                                   registry: ActionRegistry):
    palette = CommandPalette(registry)
    try:
        palette.query_edit.setText("fit to window")
        item = palette.list.topLevelItem(0)
        assert item.text(0) == "Fit to Window"
        assert item.text(1) == "View"
        assert item.text(2) == "Ctrl+0"
    finally:
        palette.close()


def test_enter_runs_the_highlighted_command(qapp, registry: ActionRegistry):
    fired: list[str] = []
    registry.bind("view.zoom_fit", lambda: fired.append("fit"))
    palette = CommandPalette(registry)
    try:
        palette.query_edit.setText("fit to window")
        spec = palette.run_current()
        assert spec is not None and spec.id == "view.zoom_fit"
        assert fired == ["fit"]
        assert not palette.isVisible()
    finally:
        palette.close()


def test_running_with_no_match_does_nothing(qapp, registry: ActionRegistry):
    palette = CommandPalette(registry)
    try:
        palette.query_edit.setText("qqqqzzzz")
        assert palette.run_current() is None
    finally:
        palette.close()


def test_the_window_palette_triggers_the_real_action(loaded):
    """From the window the palette must go through the built ``QAction``."""
    palette = loaded.show_command_palette()
    try:
        palette.query_edit.setText("circular")
        spec = palette.run_current()
        assert spec is not None and spec.id == "view.mode.circular"
        from makeyourtree.layout.params import LayoutMode
        assert loaded.session.params.mode is LayoutMode.CIRCULAR
    finally:
        palette.close()


def test_a_disabled_command_is_listed_but_refused(loaded):
    loaded.session.clear_selection()
    palette = loaded.show_command_palette()
    try:
        palette.query_edit.setText("reroot here")
        assert palette.match_ids()[0] == "tree.root.reroot"
        item = palette.list.topLevelItem(0)
        assert item.isDisabled()
        palette.list.setCurrentItem(item)
        assert palette.run_current() is None
        assert "not available" in palette.status_label.text()
    finally:
        palette.close()

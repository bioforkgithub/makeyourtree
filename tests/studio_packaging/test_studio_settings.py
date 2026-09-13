# SPDX-License-Identifier: MIT
"""Preference persistence.

Every test uses an INI-backed store in ``tmp_path`` rather than the platform
store, so the suite never reads or writes the developer's real registry entries
or preference plist. That is also the mechanism a portable build would use, so
the code path under test is a shipped one and not a test-only shim.

The recurring theme is that a settings store is untrusted input: it survives
upgrades, it can be hand-edited, and it can be truncated by a crash. Losing a
preference is acceptable; failing to start is not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray, QSettings

from makeyourtree_studio.settings import RECENT_LIMIT, THEMES, ExportSettings, Settings


@pytest.fixture
def store(tmp_path: Path) -> Settings:
    return Settings.for_file(tmp_path / "makeyourtree.ini")


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "makeyourtree.ini"


def touch(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("(:1);\n", encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------ identity


def test_default_store_is_scoped_to_the_product() -> None:
    """The organisation and application names key the on-disk location; changing
    one silently orphans every existing user's preferences."""
    assert Settings.ORGANISATION == "MakeYourTree"
    assert Settings.APPLICATION == "MakeYourTree Studio"
    settings = QSettings(Settings.ORGANISATION, Settings.APPLICATION)
    assert settings.organizationName() == "MakeYourTree"
    assert settings.applicationName() == "MakeYourTree Studio"


def test_for_file_uses_the_given_file(tmp_path: Path) -> None:
    path = tmp_path / "portable.ini"
    store = Settings.for_file(path)
    store.set_theme("dark")
    store.sync()
    assert path.is_file()
    assert Settings.for_file(path).theme() == "dark"


# -------------------------------------------------------- window persistence


def test_window_geometry_round_trips(store: Settings) -> None:
    blob = QByteArray(b"\x01\xd9geometry-blob\x00\xff")
    store.set_window_geometry(blob)
    assert store.window_geometry() == blob


def test_window_state_round_trips(store: Settings) -> None:
    blob = QByteArray(b"dock-layout\x00\x01")
    store.set_window_state(blob)
    assert store.window_state() == blob


def test_geometry_and_state_are_independent(store: Settings) -> None:
    store.set_window_geometry(QByteArray(b"geo"))
    store.set_window_state(QByteArray(b"state"))
    assert store.window_geometry() == QByteArray(b"geo")
    assert store.window_state() == QByteArray(b"state")


def test_unset_geometry_is_none(store: Settings) -> None:
    """First run must size the window itself rather than restore nothing."""
    assert store.window_geometry() is None
    assert store.window_state() is None


def test_geometry_can_be_cleared(store: Settings) -> None:
    store.set_window_geometry(QByteArray(b"geo"))
    store.set_window_geometry(None)
    assert store.window_geometry() is None


# -------------------------------------------------------------- recent files


def test_recent_files_round_trip(store: Settings, tmp_path: Path) -> None:
    a = touch(tmp_path / "a.nwk")
    b = touch(tmp_path / "b.nwk")
    store.add_recent_file(a)
    store.add_recent_file(b)
    assert store.recent_files() == [b, a]


def test_most_recent_comes_first(store: Settings, tmp_path: Path) -> None:
    paths = [touch(tmp_path / f"t{i}.nwk") for i in range(3)]
    for p in paths:
        store.add_recent_file(p)
    assert store.recent_files() == list(reversed(paths))


def test_reopening_a_file_moves_it_to_the_front_without_duplicating(
    store: Settings, tmp_path: Path
) -> None:
    a = touch(tmp_path / "a.nwk")
    b = touch(tmp_path / "b.nwk")
    store.add_recent_file(a)
    store.add_recent_file(b)
    store.add_recent_file(a)
    assert store.recent_files() == [a, b]


def test_recent_files_are_capped(store: Settings, tmp_path: Path) -> None:
    paths = [touch(tmp_path / f"t{i}.nwk") for i in range(RECENT_LIMIT + 5)]
    for p in paths:
        store.add_recent_file(p)
    recent = store.recent_files()
    assert len(recent) == RECENT_LIMIT
    assert recent[0] == paths[-1]
    assert paths[0] not in recent


def test_missing_paths_are_pruned_on_read(store: Settings, tmp_path: Path) -> None:
    """A recent entry that opens an error dialog is worse than no entry.

    Files vanish between sessions, so pruning has to happen when the menu is
    built, not only when a file is added.
    """
    kept = touch(tmp_path / "kept.nwk")
    gone = touch(tmp_path / "gone.nwk")
    store.add_recent_file(kept)
    store.add_recent_file(gone)
    Path(gone).unlink()
    assert store.recent_files() == [kept]


def test_pruning_is_written_back(store: Settings, tmp_path: Path) -> None:
    """The store must converge instead of carrying dead paths forever."""
    gone = touch(tmp_path / "gone.nwk")
    store.add_recent_file(gone)
    Path(gone).unlink()
    store.recent_files()
    assert json.loads(store.backing.value(Settings.KEY_RECENT)) == []


def test_a_directory_is_not_a_recent_file(store: Settings, tmp_path: Path) -> None:
    store.add_recent_file(tmp_path)
    assert store.recent_files() == []


def test_recent_files_are_stored_absolute(store: Settings, tmp_path: Path) -> None:
    """Relative paths would resolve against whatever directory the app was
    launched from next time."""
    touch(tmp_path / "rel.nwk")
    store.add_recent_file(tmp_path / "rel.nwk")
    assert Path(store.recent_files()[0]).is_absolute()


def test_remove_recent_file(store: Settings, tmp_path: Path) -> None:
    a = touch(tmp_path / "a.nwk")
    b = touch(tmp_path / "b.nwk")
    store.add_recent_file(a)
    store.add_recent_file(b)
    store.remove_recent_file(b)
    assert store.recent_files() == [a]


def test_clear_recent_files(store: Settings, tmp_path: Path) -> None:
    store.add_recent_file(touch(tmp_path / "a.nwk"))
    store.clear_recent_files()
    assert store.recent_files() == []


def test_a_corrupt_recent_list_reads_as_empty(store: Settings) -> None:
    store.backing.setValue(Settings.KEY_RECENT, "{not json at all")
    assert store.recent_files() == []


def test_junk_entries_in_the_recent_list_are_skipped(store: Settings, tmp_path: Path) -> None:
    kept = touch(tmp_path / "kept.nwk")
    store.backing.setValue(
        Settings.KEY_RECENT, json.dumps([None, 17, "", kept, {"a": 1}])
    )
    assert store.recent_files() == [kept]


# ---------------------------------------------------------- import directory


def test_last_import_directory_round_trips(store: Settings, tmp_path: Path) -> None:
    store.set_last_import_directory(tmp_path)
    assert store.last_import_directory() == str(tmp_path)


def test_last_import_directory_takes_the_parent_of_a_file(
    store: Settings, tmp_path: Path
) -> None:
    """Callers hand it the file they just opened; the dialog needs its folder."""
    store.set_last_import_directory(touch(tmp_path / "tree.nwk"))
    assert store.last_import_directory() == str(tmp_path)


def test_a_vanished_import_directory_reads_as_empty(
    store: Settings, tmp_path: Path
) -> None:
    """An unmounted share must not make the file dialog open on nothing."""
    directory = tmp_path / "removable"
    directory.mkdir()
    store.set_last_import_directory(directory)
    directory.rmdir()
    assert store.last_import_directory() == ""


def test_unset_import_directory_is_empty(store: Settings) -> None:
    assert store.last_import_directory() == ""


# ---------------------------------------------------------- export settings


def test_export_settings_default(store: Settings) -> None:
    assert store.export_settings() == ExportSettings()


def test_export_settings_round_trip(store: Settings, tmp_path: Path) -> None:
    chosen = ExportSettings(
        format="pdf",
        directory=str(tmp_path),
        scale=3.5,
        transparent=True,
        background="#101014",
    )
    store.set_export_settings(chosen)
    assert store.export_settings() == chosen


def test_export_settings_survive_a_new_store_object(
    store_path: Path, tmp_path: Path
) -> None:
    chosen = ExportSettings(format="svg", directory=str(tmp_path), scale=1.0)
    first = Settings.for_file(store_path)
    first.set_export_settings(chosen)
    first.sync()
    assert Settings.for_file(store_path).export_settings() == chosen


def test_corrupt_export_settings_fall_back_to_defaults(store: Settings) -> None:
    store.backing.setValue(Settings.KEY_EXPORT, "<<truncated")
    assert store.export_settings() == ExportSettings()


def test_export_settings_ignore_unknown_and_mistyped_fields(store: Settings) -> None:
    """A store written by a newer build must not break the export dialog."""
    store.backing.setValue(
        Settings.KEY_EXPORT,
        json.dumps({"format": "png", "scale": "not-a-number", "future_option": 42}),
    )
    result = store.export_settings()
    assert result.format == "png"
    assert result.scale == ExportSettings().scale


def test_export_settings_coerce_string_numbers(store: Settings) -> None:
    """INI stores can round-trip a float as text; the dialog still needs a float."""
    store.backing.setValue(Settings.KEY_EXPORT, json.dumps({"scale": "4"}))
    assert store.export_settings().scale == 4.0


def test_export_settings_are_immutable() -> None:
    """Handed out by ``export_settings()``; in-place mutation would let one
    caller change another's copy."""
    with pytest.raises(AttributeError):
        ExportSettings().format = "pdf"  # type: ignore[misc]


# -------------------------------------------------------------------- theme


def test_theme_round_trips(store: Settings) -> None:
    store.set_theme("dark")
    assert store.theme() == "dark"


def test_theme_defaults_to_the_first_known_choice(store: Settings) -> None:
    assert store.theme() == THEMES[0]


def test_an_unknown_theme_is_ignored_on_write(store: Settings) -> None:
    store.set_theme("light")
    store.set_theme("solarized-midnight")
    assert store.theme() == "light"


def test_an_unknown_theme_in_the_store_falls_back(store: Settings) -> None:
    """A theme removed in a later release must not leave the UI unstyled."""
    store.backing.setValue(Settings.KEY_THEME, "removed-in-v2")
    assert store.theme() == THEMES[0]


# ---------------------------------------------------------------- shortcuts


def test_shortcuts_round_trip(store: Settings) -> None:
    overrides = {"file.open": "Ctrl+Shift+O", "tree.root.midpoint": "F8"}
    store.save_shortcuts(overrides)
    assert store.load_shortcuts() == overrides


def test_shortcuts_survive_a_new_store_object(store_path: Path) -> None:
    Settings.for_file(store_path).save_shortcuts({"view.fit": "Ctrl+9"})
    assert Settings.for_file(store_path).load_shortcuts() == {"view.fit": "Ctrl+9"}


def test_no_shortcut_overrides_by_default(store: Settings) -> None:
    """Only differences from the built-in defaults are stored, so that a shortcut
    corrected in a later release reaches users who never customised it."""
    assert store.load_shortcuts() == {}


def test_saving_shortcuts_replaces_rather_than_merges(store: Settings) -> None:
    """The editor writes the full override set; merging would resurrect bindings
    the user just cleared."""
    store.save_shortcuts({"a.one": "Ctrl+1", "a.two": "Ctrl+2"})
    store.save_shortcuts({"a.one": "Ctrl+1"})
    assert store.load_shortcuts() == {"a.one": "Ctrl+1"}


def test_an_empty_sequence_is_a_deliberate_unbinding(store: Settings) -> None:
    store.save_shortcuts({"tree.prune": ""})
    assert store.load_shortcuts() == {"tree.prune": ""}


def test_a_corrupt_shortcut_table_reads_as_empty(store: Settings) -> None:
    store.backing.setValue(Settings.KEY_SHORTCUTS, "]]not json[[")
    assert store.load_shortcuts() == {}


def test_a_shortcut_table_of_the_wrong_shape_reads_as_empty(store: Settings) -> None:
    store.backing.setValue(Settings.KEY_SHORTCUTS, json.dumps(["Ctrl+O"]))
    assert store.load_shortcuts() == {}


def test_non_string_shortcut_values_are_dropped(store: Settings) -> None:
    store.backing.setValue(
        Settings.KEY_SHORTCUTS, json.dumps({"a.one": "Ctrl+1", "a.two": 7, "": "Ctrl+3"})
    )
    assert store.load_shortcuts() == {"a.one": "Ctrl+1"}


# ------------------------------------------------- shortcuts and the registry


def test_apply_shortcuts_rebinds_the_registry(tmp_path: Path) -> None:
    from makeyourtree_studio.actions import ActionRegistry, ActionSpec

    registry = ActionRegistry()
    registry.add(ActionSpec(id="file.open", text="Open", shortcut="Ctrl+O"))
    registry.add(ActionSpec(id="view.fit", text="Fit", shortcut="Ctrl+0"))

    settings = Settings.for_file(tmp_path / "s.ini")
    settings.save_shortcuts({"file.open": "Ctrl+Shift+O"})
    applied = settings.apply_shortcuts(registry)

    assert applied == 1
    assert registry.spec("file.open").shortcut == "Ctrl+Shift+O"
    assert registry.spec("view.fit").shortcut == "Ctrl+0"


def test_apply_shortcuts_skips_actions_that_no_longer_exist(tmp_path: Path) -> None:
    """A downgrade, or a removed feature, must not make the app unlaunchable."""
    from makeyourtree_studio.actions import ActionRegistry, ActionSpec

    registry = ActionRegistry()
    registry.add(ActionSpec(id="file.open", text="Open", shortcut="Ctrl+O"))

    settings = Settings.for_file(tmp_path / "s.ini")
    settings.save_shortcuts({"gone.forever": "Ctrl+G", "file.open": "F2"})
    assert settings.apply_shortcuts(registry) == 1
    assert registry.spec("file.open").shortcut == "F2"


def test_apply_shortcuts_can_unbind(tmp_path: Path) -> None:
    from makeyourtree_studio.actions import ActionRegistry, ActionSpec

    registry = ActionRegistry()
    registry.add(ActionSpec(id="tree.prune", text="Prune", shortcut="Delete"))

    settings = Settings.for_file(tmp_path / "s.ini")
    settings.save_shortcuts({"tree.prune": ""})
    settings.apply_shortcuts(registry)
    assert registry.spec("tree.prune").shortcut is None


def test_collect_shortcuts_stores_only_the_differences(tmp_path: Path) -> None:
    from makeyourtree_studio.actions import ActionRegistry, ActionSpec

    registry = ActionRegistry()
    registry.add(ActionSpec(id="file.open", text="Open", shortcut="Ctrl+O"))
    registry.add(ActionSpec(id="view.fit", text="Fit", shortcut="Ctrl+0"))
    defaults = {s.id: s.shortcut for s in registry.specs()}

    registry.set_shortcut("view.fit", "F5")
    settings = Settings.for_file(tmp_path / "s.ini")
    settings.collect_shortcuts(registry, defaults)

    assert settings.load_shortcuts() == {"view.fit": "F5"}


def test_collect_then_apply_is_a_round_trip(tmp_path: Path) -> None:
    from makeyourtree_studio.actions import ActionRegistry, ActionSpec

    def fresh() -> ActionRegistry:
        registry = ActionRegistry()
        registry.add(ActionSpec(id="file.open", text="Open", shortcut="Ctrl+O"))
        registry.add(ActionSpec(id="view.fit", text="Fit", shortcut="Ctrl+0"))
        registry.add(ActionSpec(id="tree.prune", text="Prune", shortcut="Delete"))
        return registry

    original = fresh()
    defaults = {s.id: s.shortcut for s in original.specs()}
    original.set_shortcut("view.fit", "F5")
    original.set_shortcut("tree.prune", None)

    settings = Settings.for_file(tmp_path / "s.ini")
    settings.collect_shortcuts(original, defaults)

    restored = fresh()
    settings.apply_shortcuts(restored)
    assert {s.id: s.shortcut for s in restored.specs()} == {
        s.id: s.shortcut for s in original.specs()
    }


# -------------------------------------------------------------- robustness


def test_a_truncated_settings_file_does_not_raise(tmp_path: Path) -> None:
    """A crash during a write leaves a half-written file; the next launch must
    still reach the main window."""
    path = tmp_path / "broken.ini"
    path.write_bytes(b"\x00\x01\x02 not an ini file at all \xff\xfe[unclosed")
    store = Settings.for_file(path)
    assert store.recent_files() == []
    assert store.load_shortcuts() == {}
    assert store.export_settings() == ExportSettings()
    assert store.theme() == THEMES[0]
    assert store.window_geometry() is None
    assert store.last_import_directory() == ""


def test_clear_resets_every_preference(store: Settings, tmp_path: Path) -> None:
    store.set_theme("dark")
    store.add_recent_file(touch(tmp_path / "a.nwk"))
    store.save_shortcuts({"file.open": "F1"})
    store.clear()
    assert store.theme() == THEMES[0]
    assert store.recent_files() == []
    assert store.load_shortcuts() == {}

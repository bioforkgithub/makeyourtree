# SPDX-License-Identifier: MIT
"""Persisted user preferences, as a typed façade over ``QSettings``.

``QSettings`` is stringly-typed and platform-dependent: the same key comes back as
``str`` from an INI file, as ``QByteArray`` from the Windows registry, and as
whatever a hand-edited file happens to contain. Letting that leak into the window
and the dialogs would spread ``isinstance`` checks across the UI, so every read is
funnelled through this module and returns a real Python type or a documented
default.

The second reason this exists is robustness. A settings store is user-writable
state that outlives the install: it can be truncated by a crash, edited by hand,
or written by a newer build. **Losing preferences must never stop the application
from starting**, so every accessor catches its own failures and falls back to the
default rather than propagating. Nothing in here may raise on read.

Structured values (recent files, shortcut overrides, export settings) are stored
as JSON strings rather than as native ``QSettings`` lists and maps. Native lists
do not round-trip faithfully across backends — a one-element list returns as a
bare string on the INI backend — whereas JSON is identical everywhere and has one
obvious failure mode we can catch.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Final, Mapping

from PySide6.QtCore import QByteArray, QSettings

__all__ = ["ExportSettings", "Settings", "INTERNAL_LABEL_MODES"]


#: Themes the appearance menu offers. A value outside this set is treated as a
#: corrupt store and replaced by the default rather than handed to the UI.
THEMES: Final[tuple[str, ...]] = ("system", "light", "dark")

#: How a numeric label on an internal node is read. ``auto`` is the reader's
#: own default: treat it as branch support and record a diagnostic saying so.
INTERNAL_LABEL_MODES: Final[tuple[str, ...]] = ("auto", "support", "name")

#: How many recent files the File menu keeps. Long enough to be useful, short
#: enough that pruning missing paths on every read stays cheap.
RECENT_LIMIT: Final[int] = 12


# --------------------------------------------------------------- export state


@dataclass(frozen=True, slots=True)
class ExportSettings:
    """The choices the export dialog should re-offer next time it opens.

    Frozen because it is handed out of :meth:`Settings.export_settings` and must
    not be mutated in place by one caller behind another's back; use
    :func:`dataclasses.replace` to derive a changed copy.
    """

    format: str = "png"
    """Lower-case extension without the dot: ``png``, ``pdf`` or ``svg``."""
    directory: str = ""
    """Last directory exported into. Empty means "ask the platform"."""
    scale: float = 2.0
    """Raster oversampling factor. Ignored by the vector formats."""
    transparent: bool = False
    background: str = "#ffffff"
    """CSS-style hex colour used when *transparent* is false."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExportSettings":
        """Build from an untrusted mapping, ignoring junk.

        Unknown keys are dropped and wrongly typed values fall back to the field
        default, so a store written by a different build never breaks the dialog.
        """
        out = cls()
        if not isinstance(data, Mapping):
            return out
        fields: dict[str, Any] = {}
        for name, default in out.to_dict().items():
            if name not in data:
                continue
            value = data[name]
            try:
                if isinstance(default, bool):
                    fields[name] = bool(value)
                elif isinstance(default, float):
                    fields[name] = float(value)
                elif isinstance(default, str):
                    fields[name] = str(value)
            except (TypeError, ValueError):
                continue
        return replace(out, **fields)


# ------------------------------------------------------------------- settings


class Settings:
    """Typed access to the persisted preferences of one user."""

    ORGANISATION: Final[str] = "MakeYourTree"
    APPLICATION: Final[str] = "MakeYourTree Studio"

    # Keys are grouped by area and are part of the on-disk contract: renaming one
    # silently discards a user's preference, so treat them as frozen.
    KEY_GEOMETRY: Final[str] = "window/geometry"
    KEY_WINDOW_STATE: Final[str] = "window/state"
    KEY_RECENT: Final[str] = "files/recent"
    KEY_IMPORT_DIR: Final[str] = "files/last_import_dir"
    KEY_EXPORT: Final[str] = "export/last"
    KEY_THEME: Final[str] = "appearance/theme"
    KEY_INTERNAL_LABELS: Final[str] = "reading/internal_labels"
    KEY_SHORTCUTS: Final[str] = "shortcuts/overrides"

    def __init__(self, backing: QSettings | None = None) -> None:
        """Wrap *backing*, or the per-user store for this organisation.

        Tests and portable installs pass their own store; the application passes
        nothing and gets the platform-native location.
        """
        self._s = backing if backing is not None else QSettings(
            self.ORGANISATION, self.APPLICATION
        )

    @classmethod
    def for_file(cls, path: str | os.PathLike[str]) -> "Settings":
        """A store backed by one INI file.

        Used by the tests, and by a future portable build that must keep its state
        beside the executable instead of in the user profile.
        """
        return cls(QSettings(str(path), QSettings.Format.IniFormat))

    @property
    def backing(self) -> QSettings:
        """The underlying store, for the rare caller that needs a raw key."""
        return self._s

    def sync(self) -> None:
        """Flush to disk. Called on quit; ``QSettings`` also flushes lazily."""
        try:
            self._s.sync()
        except (OSError, RuntimeError):
            pass

    def clear(self) -> None:
        """Reset every preference — the "restore defaults" command."""
        try:
            self._s.clear()
            self._s.sync()
        except (OSError, RuntimeError):
            pass

    # ---------------------------------------------------------- raw helpers

    def _raw(self, key: str) -> Any:
        try:
            return self._s.value(key)
        except (RuntimeError, ValueError, TypeError):
            return None

    def _set(self, key: str, value: Any) -> None:
        try:
            self._s.setValue(key, value)
        except (RuntimeError, ValueError, TypeError):
            pass

    def _json(self, key: str, default: Any) -> Any:
        """Decode a JSON-encoded value, returning *default* on anything odd.

        This is the single place a corrupt store is absorbed; every structured
        accessor goes through it.
        """
        raw = self._raw(key)
        if isinstance(raw, QByteArray):
            raw = bytes(raw.data()).decode("utf-8", errors="replace")
        if not isinstance(raw, str) or not raw:
            return default
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return default

    def _set_json(self, key: str, value: Any) -> None:
        try:
            self._set(key, json.dumps(value, ensure_ascii=False))
        except (TypeError, ValueError):
            pass

    # --------------------------------------------------- window geometry

    def window_geometry(self) -> QByteArray | None:
        """Saved ``QMainWindow.saveGeometry()`` blob, or ``None``.

        ``None`` means "no usable saved geometry" and the window should size
        itself; that covers first run and a store whose value is the wrong type.
        """
        return _as_bytearray(self._raw(self.KEY_GEOMETRY))

    def set_window_geometry(self, data: QByteArray | bytes | None) -> None:
        if data is None:
            self._remove(self.KEY_GEOMETRY)
        else:
            self._set(self.KEY_GEOMETRY, QByteArray(bytes(data)))

    def window_state(self) -> QByteArray | None:
        """Saved ``QMainWindow.saveState()`` blob — the dock layout."""
        return _as_bytearray(self._raw(self.KEY_WINDOW_STATE))

    def set_window_state(self, data: QByteArray | bytes | None) -> None:
        if data is None:
            self._remove(self.KEY_WINDOW_STATE)
        else:
            self._set(self.KEY_WINDOW_STATE, QByteArray(bytes(data)))

    def _remove(self, key: str) -> None:
        try:
            self._s.remove(key)
        except (RuntimeError, ValueError):
            pass

    # ------------------------------------------------------- recent files

    def recent_files(self) -> list[str]:
        """Most-recent-first paths that still exist on disk.

        Pruning happens on *read* rather than on open, because a file can vanish
        while the application is running or between sessions, and a menu entry
        that opens an error dialog is worse than no entry. The pruned list is
        written back so the store converges instead of accumulating dead paths.
        """
        stored = self._json(self.KEY_RECENT, [])
        if not isinstance(stored, list):
            stored = []
        kept: list[str] = []
        seen: set[str] = set()
        for item in stored:
            if not isinstance(item, str) or not item:
                continue
            key = _dedup_key(item)
            if key in seen:
                continue
            try:
                if not Path(item).is_file():
                    continue
            except OSError:
                continue
            seen.add(key)
            kept.append(item)
            if len(kept) >= RECENT_LIMIT:
                break
        if kept != stored:
            self._set_json(self.KEY_RECENT, kept)
        return kept

    def add_recent_file(self, path: str | os.PathLike[str]) -> list[str]:
        """Push *path* to the front, deduplicated and capped. Returns the list.

        Deduplication compares case-folded absolute paths so that Windows does not
        show the same file twice under different casing, but the stored form keeps
        the caller's casing because that is what the user recognises in the menu.
        """
        try:
            absolute = str(Path(path).absolute())
        except (OSError, ValueError):
            return self.recent_files()
        key = _dedup_key(absolute)
        current = [p for p in self._existing_recent() if _dedup_key(p) != key]
        current.insert(0, absolute)
        del current[RECENT_LIMIT:]
        self._set_json(self.KEY_RECENT, current)
        return current

    def remove_recent_file(self, path: str | os.PathLike[str]) -> list[str]:
        key = _dedup_key(str(path))
        current = [p for p in self._existing_recent() if _dedup_key(p) != key]
        self._set_json(self.KEY_RECENT, current)
        return current

    def clear_recent_files(self) -> None:
        self._set_json(self.KEY_RECENT, [])

    def _existing_recent(self) -> list[str]:
        """Recent list without the existence filter.

        ``add_recent_file`` must not drop entries for files that are merely
        offline right now (a network share, an unmounted volume): a write is not
        the moment to garbage-collect. Only :meth:`recent_files` prunes.
        """
        stored = self._json(self.KEY_RECENT, [])
        if not isinstance(stored, list):
            return []
        return [p for p in stored if isinstance(p, str) and p]

    # ------------------------------------------------------ import/export

    def last_import_directory(self) -> str:
        """Directory the file dialog should start in, or ``""`` if unusable."""
        raw = self._raw(self.KEY_IMPORT_DIR)
        if not isinstance(raw, str) or not raw:
            return ""
        try:
            return raw if Path(raw).is_dir() else ""
        except OSError:
            return ""

    def set_last_import_directory(self, path: str | os.PathLike[str]) -> None:
        """Record *path*, or its parent if a file was passed."""
        try:
            p = Path(path)
            directory = p if p.is_dir() else p.parent
            self._set(self.KEY_IMPORT_DIR, str(directory))
        except (OSError, ValueError):
            pass

    def export_settings(self) -> ExportSettings:
        return ExportSettings.from_dict(self._json(self.KEY_EXPORT, {}))

    def set_export_settings(self, settings: ExportSettings) -> None:
        self._set_json(self.KEY_EXPORT, settings.to_dict())

    # -------------------------------------------------------------- theme

    def theme(self) -> str:
        """One of :data:`THEMES`; anything else is treated as unset."""
        raw = self._raw(self.KEY_THEME)
        return raw if isinstance(raw, str) and raw in THEMES else THEMES[0]

    def set_theme(self, name: str) -> None:
        """Store *name*, ignoring values the application cannot honour."""
        if name in THEMES:
            self._set(self.KEY_THEME, name)

    # ----------------------------------------------------- reading policy

    def internal_labels(self) -> str:
        """How a numeric label on an internal node should be read.

        The reader's default, ``auto``, treats such a label as branch support
        and says so.  That is right for the majority of files and wrong for a
        tree whose clades are genuinely numbered, and until this preference
        existed the only way to change it was a Python keyword argument.
        """
        raw = self._raw(self.KEY_INTERNAL_LABELS)
        if isinstance(raw, str) and raw in INTERNAL_LABEL_MODES:
            return raw
        return INTERNAL_LABEL_MODES[0]

    def set_internal_labels(self, mode: str) -> None:
        if mode in INTERNAL_LABEL_MODES:
            self._set(self.KEY_INTERNAL_LABELS, mode)

    # ---------------------------------------------------------- shortcuts

    def load_shortcuts(self) -> dict[str, str]:
        """User overrides, keyed by :attr:`ActionSpec.id`.

        Only the *differences* from the built-in defaults are stored. Storing the
        whole table would freeze a user's bindings at the version they first ran,
        so a shortcut added or corrected in a later release would never reach
        them. An empty string is a meaningful value: it means "this action has
        been deliberately unbound".
        """
        stored = self._json(self.KEY_SHORTCUTS, {})
        if not isinstance(stored, dict):
            return {}
        return {
            str(k): str(v)
            for k, v in stored.items()
            if isinstance(k, str) and k and isinstance(v, str)
        }

    def save_shortcuts(self, mapping: Mapping[str, str]) -> None:
        """Replace the override table wholesale.

        The shortcut editor always writes the complete set of overrides it knows
        about, so a merge here would resurrect bindings the user just cleared.
        """
        clean = {
            str(k): str(v)
            for k, v in mapping.items()
            if isinstance(k, str) and k
        }
        self._set_json(self.KEY_SHORTCUTS, clean)

    def apply_shortcuts(self, registry: Any) -> int:
        """Push stored overrides onto an ``ActionRegistry``. Returns how many.

        Overrides naming an action that no longer exists are skipped rather than
        raising: action ids are stable, but a downgrade or a removed feature must
        not make the application unlaunchable.
        """
        applied = 0
        for action_id, sequence in self.load_shortcuts().items():
            if action_id not in registry:
                continue
            registry.set_shortcut(action_id, sequence or None)
            applied += 1
        return applied

    def collect_shortcuts(self, registry: Any, defaults: Mapping[str, str | None]) -> None:
        """Store the registry's bindings that differ from *defaults*.

        *defaults* is the shortcut of every spec as declared in code, captured
        before any override was applied.
        """
        overrides: dict[str, str] = {}
        for spec in registry.specs():
            current = spec.shortcut or ""
            original = defaults.get(spec.id) or ""
            if current != original:
                overrides[spec.id] = current
        self.save_shortcuts(overrides)


# ------------------------------------------------------------------- helpers


def _as_bytearray(raw: Any) -> QByteArray | None:
    """Coerce a stored blob to ``QByteArray``, or ``None`` if it is not one.

    The registry backend returns ``QByteArray`` and the INI backend can return a
    ``str`` or ``bytes`` depending on how the file was written, so all three are
    accepted and everything else is rejected as corrupt.
    """
    if isinstance(raw, QByteArray):
        return raw if not raw.isEmpty() else None
    if isinstance(raw, (bytes, bytearray)):
        return QByteArray(bytes(raw)) if raw else None
    if isinstance(raw, str) and raw:
        return QByteArray(raw.encode("utf-8", errors="replace"))
    return None


def _dedup_key(path: str) -> str:
    """Comparison key for two paths that name the same file.

    ``normcase`` folds case and separators on Windows and is a no-op elsewhere,
    which is exactly the platform behaviour we want.
    """
    try:
        return os.path.normcase(os.path.abspath(path))
    except (OSError, ValueError):
        return path

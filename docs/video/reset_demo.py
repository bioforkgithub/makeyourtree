# SPDX-License-Identifier: MIT
"""Put the application back to first-run state before recording.

Run with ``python docs/video/reset_demo.py``.

The application remembers your last layout mode, theme, window geometry, panel
visibility and recent files. That is right for daily use and wrong for a
recording: the video opens on whatever you were last doing, which for the first
take of this tutorial was an unrooted layout left over from testing. Nobody
notices while recording and everybody notices on playback.

This clears the saved settings and reports what it removed, so a take starts
from the same state every time and a retake matches the take before it.

It does not touch your documents, your projects or anything in ``examples/``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def settings_locations() -> list[Path]:
    """Every place the studio's settings could live, per platform.

    Qt chooses by platform, and the organisation and application names come from
    ``Settings``, so they are read from the code rather than repeated here --
    a renamed application would otherwise leave this quietly clearing nothing.
    """
    from makeyourtree_studio.settings import Settings

    org, app = Settings.ORGANISATION, Settings.APPLICATION
    home = Path.home()
    candidates = [
        # Windows: QSettings uses the registry, handled separately below.
        home / ".config" / org / f"{app}.conf",          # Linux
        home / ".config" / org / app,                     # Linux, directory form
        home / "Library" / "Preferences" / f"com.{org}.{app}.plist",  # macOS
        home / "Library" / "Preferences" / f"{org}.{app}.plist",
    ]
    return [p for p in candidates if p.exists()]


def registry_key() -> str | None:
    """The registry path holding the settings on Windows, if it exists.

    Checked separately from removal so that --dry-run can report it. Without
    this the dry run said "nothing to clear" on the one platform where the
    settings are never files, which is exactly the reassurance you do not want
    before a take.
    """
    if sys.platform != "win32":
        return None
    import winreg

    from makeyourtree_studio.settings import Settings

    path = rf"Software\{Settings.ORGANISATION}\{Settings.APPLICATION}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path):
            return path
    except OSError:
        return None


def clear_registry() -> bool:
    """Remove the Windows registry key, where QSettings puts things there."""
    if sys.platform != "win32":
        return False
    import winreg

    from makeyourtree_studio.settings import Settings

    path = f"Software\\{Settings.ORGANISATION}\\{Settings.APPLICATION}"
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        # A key with subkeys cannot be deleted in one call; walk it.
        try:
            _delete_tree(winreg.HKEY_CURRENT_USER, path)
            return True
        except OSError:
            return False


def _delete_tree(root, path: str) -> None:
    import winreg

    with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
        while True:
            try:
                child = winreg.EnumKey(key, 0)
            except OSError:
                break
            _delete_tree(root, f"{path}\\{child}")
    winreg.DeleteKey(root, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reset-demo",
        description="Clear saved settings so a recording starts from first-run "
                    "state.")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be removed, remove nothing")
    args = parser.parse_args(argv)

    removed: list[str] = []
    key = registry_key()
    if key and args.dry_run:
        removed.append(fr"HKCU\{key}")
    for path in settings_locations():
        if args.dry_run:
            removed.append(str(path))
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        removed.append(str(path))

    if not args.dry_run and clear_registry():
        from makeyourtree_studio.settings import Settings
        removed.append(
            fr"HKCU\Software\{Settings.ORGANISATION}\{Settings.APPLICATION}")

    if removed:
        print("Would clear:" if args.dry_run else "Cleared:")
        for item in removed:
            print(f"  {item}")
    else:
        print("Nothing to clear -- already at first-run state.")

    print("\nStart the app and confirm before recording:")
    print("  * it opens on Rectangular, not whatever you used last")
    print("  * the theme is light")
    print("  * File > Open Recent is empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

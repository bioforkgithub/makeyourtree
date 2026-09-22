# SPDX-License-Identifier: MIT
"""Every menu, option and button a guide plan names must exist in the studio.

A plan that says "choose Cladogram Aligned in the Branches drop-down" is only
help if that drop-down exists and offers that item. The recipe spells those
names by hand -- the core cannot import the toolkit -- so they can drift from
the interface silently. This walks the real window and dialogs, collects every
visible label, and checks each bold name in every plan the interview can
produce against them, including that a menu path names an item in that menu
and that its shortcut is the one the plan quotes.
"""

from __future__ import annotations

import itertools
import re

from PySide6.QtWidgets import (QAbstractButton, QComboBox, QDockWidget,
                               QDoubleSpinBox, QGroupBox, QLabel, QLineEdit,
                               QWidget)

from makeyourtree.guide.questions import QUESTIONS
from makeyourtree.guide.recipe import build_plan
from makeyourtree.tracks import track_types
from makeyourtree_studio.dialogs.export_dialog import ExportDialog
from makeyourtree_studio.dialogs.import_dialog import ImportDialog
from makeyourtree_studio.panels.tracks_panel import TrackTypeDialog

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MENU_PATH = re.compile(
    r"\*\*(\w+) > ([^*]+)\*\*\s*\((?:shortcut: )?([^)]+)\)")


def _texts(root: QWidget) -> set[str]:
    found: set[str] = set()
    for w in root.findChildren(QWidget):
        if isinstance(w, QLabel):
            found.add(w.text())
        elif isinstance(w, QAbstractButton):
            found.add(w.text())
        elif isinstance(w, QGroupBox):
            found.add(w.title())
        elif isinstance(w, QDockWidget):
            found.add(w.windowTitle())
        elif isinstance(w, QComboBox):
            found.update(w.itemText(i) for i in range(w.count()))
        elif isinstance(w, QLineEdit):
            found.add(w.placeholderText())
        if isinstance(w, QDoubleSpinBox):
            found.add(w.specialValueText())
    found.add(root.windowTitle())
    return {t.replace("&", "").strip() for t in found if t}


def _menus(window) -> dict[str, dict[str, str]]:
    """Menu title -> {item text: shortcut}."""
    out: dict[str, dict[str, str]] = {}
    for top in window.menuBar().actions():
        menu = top.menu()
        if menu is None:
            continue
        items = {a.text().replace("&", ""): a.shortcut().toString()
                 for a in menu.actions() if a.text()}
        out[top.text().replace("&", "")] = items
    return out


def _every_plan():
    """One plan per answer to every question, on top of a busy baseline."""
    base = {"goal": "paper", "tip_count": "hundreds",
            "branch_meaning": "unsure", "rooting": "outgroup",
            "extra_data": [c.value for c in
                           next(q for q in QUESTIONS if q.id == "extra_data").choices
                           if c.value != "none"],
            "extras": ["everything", "dark"], "label_tips": "some",
            "shape": "recommend", "colour_safe": "yes"}
    yield build_plan(base)
    for question in QUESTIONS:
        for choice in question.choices:
            value = [choice.value] if question.multi else choice.value
            yield build_plan({**base, question.id: value})
    for shape, tips in itertools.product(("rectangular", "circular", "unrooted"),
                                         ("tens", "thousands")):
        yield build_plan({**base, "shape": shape, "tip_count": tips})


def test_every_name_a_plan_uses_is_on_screen(window, qapp):
    names = _texts(window)
    menus = _menus(window)
    names.update(menus)
    for items in menus.values():
        names.update(items)
    for dialog in (ImportDialog(window.session, window),
                   ExportDialog(window.session, window),
                   TrackTypeDialog(window)):
        names |= _texts(dialog)
        dialog.deleteLater()
    for klass in track_types():
        names.add(klass.display_name)
        names.update(key.replace("_", " ") for key in klass.default_options())

    missing: set[str] = set()
    for plan in _every_plan():
        for step in plan.steps:
            for phrase in _BOLD.findall(step.detail):
                if phrase.startswith("How to do it in"):
                    continue
                for part in phrase.split(" > "):
                    if part not in names:
                        missing.add(f"{step.id}: {part!r}")
    assert not missing, sorted(missing)


def test_every_menu_path_and_shortcut_matches_the_menus(window, qapp):
    menus = _menus(window)
    wrong: set[str] = set()
    checked = 0
    for plan in _every_plan():
        for step in plan.steps:
            for menu, item, keys in _MENU_PATH.findall(step.detail):
                checked += 1
                if item not in menus.get(menu, {}):
                    wrong.add(f"{menu} > {item}: no such item")
                elif menus[menu][item] != keys:
                    wrong.add(f"{menu} > {item}: plan says {keys!r}, "
                              f"menu has {menus[menu][item]!r}")
    assert checked > 20, "the pattern stopped matching the plan's wording"
    assert not wrong, sorted(wrong)

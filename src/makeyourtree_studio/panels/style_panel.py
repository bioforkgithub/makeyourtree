# SPDX-License-Identifier: MIT
"""Layout and appearance controls, plus per-selection styling.

Two kinds of change live side by side here and they are routed differently on
purpose.

*Document-wide* settings -- layout mode, spacing, polar geometry, label and
support display, theme -- go through :meth:`Session.set_params` and
:meth:`Session.set_theme_attr`. They are view settings, not data: they are saved
with the project but they are not tree edits, so they do not belong on the undo
stack, where they would bury the user's actual edits under a hundred entries of
"row spacing 16.2".

*Per-selection* styling is different. Colouring a clade is an authored decision
about the figure, it survives export, and a user who does it by accident expects
Ctrl+Z to take it back. Those go through :meth:`Session.do` as
:class:`~makeyourtree_studio.models.SetNodeStyleCommand`.

Dragging a slider emits one signal per pixel. Every such drag is issued with
``coalesce=True`` so the command stack folds the whole gesture into the single
entry that ``SetNodeStyleCommand.merge_with`` produces -- otherwise one drag
would consume the entire 500-entry history and push every real edit off the end.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

from makeyourtree.layout.params import (BranchMode, LayoutMode, ParentRule,
                                    UnrootedMethod)
from makeyourtree.ops.command import CompositeCommand
from makeyourtree.style.color import Color
from makeyourtree.style.theme import DARK, LIGHT, Theme

from ..models import SetNodeStyleCommand
from ..session import Session
from . import ColorButton

__all__ = ["StylePanel"]

_STYLE_KEYS = ("branch_color", "branch_width", "label_color", "label_bold",
               "label_italic", "clade_fill")

_WIDTH_STEPS = 10.0
"""Slider steps per unit of branch width. Integer sliders only, so widths are
quantised to a tenth of a scene unit -- finer than the eye resolves at any
sensible zoom, and it keeps the drag responsive."""


class StylePanel(QWidget):
    """Layout, appearance, and styling for whatever is selected."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._loading = False
        self._committing = 0

        body = QWidget(self)
        self._form_host = body
        vbox = QVBoxLayout(body)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.addWidget(self._build_layout_group())
        vbox.addWidget(self._build_polar_group())
        vbox.addWidget(self._build_unrooted_group())
        vbox.addWidget(self._build_label_group())
        vbox.addWidget(self._build_support_group())
        vbox.addWidget(self._build_theme_group())
        vbox.addWidget(self._build_selection_group())
        vbox.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        session.documentReplaced.connect(self.reload)
        session.selectionChanged.connect(self._reload_selection)
        # Layout mode, align-tips and the theme can all be changed from the
        # menu, the toolbar or a bare-key shortcut. Without this the panel goes
        # on claiming "Rectangular" while the canvas draws a fan -- it has to be
        # a view of the document, not a second copy of it. `_committing` keeps
        # the panel's own writes from bouncing straight back into its widgets
        # mid-keystroke.
        session.dirtied.connect(self._on_dirtied)
        self.reload()

    # ----------------------------------------------------------- properties

    @property
    def session(self) -> Session:
        return self._session

    # ------------------------------------------------------------- building

    @staticmethod
    def _spin(lo: float, hi: float, step: float, decimals: int = 2,
              special: str = "") -> QDoubleSpinBox:
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.setDecimals(decimals)
        w.setKeyboardTracking(False)
        if special:
            w.setSpecialValueText(special)
        return w

    @staticmethod
    def _enum_combo(enum_cls: type) -> QComboBox:
        """Combo whose item data is the enum member's *value*, not its index.

        The value, because every layout enum here subclasses ``str`` and Qt
        stores such a member as a plain Python string -- so reading the member
        back out of the combo would hand ``LayoutParams`` a bare string, and
        ``params.mode.is_polar`` would then fail on an attribute a string does
        not have. The write-back re-inflates the value through ``enum_cls``.
        """
        w = QComboBox()
        for member in enum_cls:
            w.addItem(str(member.value).replace("-", " ").title(), member.value)
        return w

    @staticmethod
    def _enum_of(combo: QComboBox, enum_cls: type) -> Any:
        return enum_cls(combo.currentData())

    def _build_layout_group(self) -> QGroupBox:
        box = QGroupBox("Layout", self._form_host)
        form = QFormLayout(box)

        self.mode_combo = self._enum_combo(LayoutMode)
        self.branch_mode_combo = self._enum_combo(BranchMode)
        self.parent_rule_combo = self._enum_combo(ParentRule)
        self.width_spin = self._spin(50.0, 20000.0, 25.0, 1)
        self.row_spacing_spin = self._spin(1.0, 400.0, 1.0, 2)
        self.x_scale_spin = self._spin(0.0, 100000.0, 1.0, 3, special="fit")
        self.align_tips_check = QCheckBox("Align tips")
        self.guide_lines_check = QCheckBox("Guide lines")

        self.mode_combo.currentIndexChanged.connect(
            lambda: self._param("mode",
                                self._enum_of(self.mode_combo, LayoutMode)))
        self.branch_mode_combo.currentIndexChanged.connect(
            lambda: self._param("branch_mode",
                                self._enum_of(self.branch_mode_combo,
                                              BranchMode)))
        self.parent_rule_combo.currentIndexChanged.connect(
            lambda: self._param("parent_rule",
                                self._enum_of(self.parent_rule_combo,
                                              ParentRule)))
        self.width_spin.valueChanged.connect(
            lambda v: self._param("width", float(v)))
        self.row_spacing_spin.valueChanged.connect(
            lambda v: self._param("row_spacing", float(v)))
        self.x_scale_spin.valueChanged.connect(
            lambda v: self._param("x_scale", None if v <= 0.0 else float(v)))
        self.align_tips_check.toggled.connect(
            lambda on: self._param("align_tips", bool(on)))
        self.guide_lines_check.toggled.connect(
            lambda on: self._param("guide_lines", bool(on)))

        form.addRow("Mode", self.mode_combo)
        form.addRow("Branches", self.branch_mode_combo)
        form.addRow("Parent rule", self.parent_rule_combo)
        form.addRow("Width", self.width_spin)
        form.addRow("Row spacing", self.row_spacing_spin)
        form.addRow("X scale", self.x_scale_spin)
        form.addRow("", self.align_tips_check)
        form.addRow("", self.guide_lines_check)
        return box

    def _build_polar_group(self) -> QGroupBox:
        box = QGroupBox("Circular", self._form_host)
        form = QFormLayout(box)

        self.start_angle_spin = self._spin(-360.0, 360.0, 5.0, 1)
        self.arc_spin = self._spin(1.0, 360.0, 5.0, 1)
        self.inner_radius_spin = self._spin(0.0, 0.9, 0.01, 3)
        self.direction_combo = QComboBox()
        self.direction_combo.addItem("Clockwise", 1)
        self.direction_combo.addItem("Anticlockwise", -1)
        self.rotate_labels_check = QCheckBox("Rotate labels with the radius")

        self.start_angle_spin.valueChanged.connect(
            lambda v: self._param("start_angle", float(v)))
        self.arc_spin.valueChanged.connect(
            lambda v: self._param("arc", float(v)))
        self.inner_radius_spin.valueChanged.connect(
            lambda v: self._param("inner_radius", float(v)))
        self.direction_combo.currentIndexChanged.connect(
            lambda: self._param("direction",
                                int(self.direction_combo.currentData())))
        self.rotate_labels_check.toggled.connect(
            lambda on: self._param("rotate_labels", bool(on)))

        form.addRow("Start angle", self.start_angle_spin)
        form.addRow("Arc", self.arc_spin)
        form.addRow("Inner radius", self.inner_radius_spin)
        form.addRow("Direction", self.direction_combo)
        form.addRow("", self.rotate_labels_check)
        return box

    def _build_unrooted_group(self) -> QGroupBox:
        box = QGroupBox("Unrooted", self._form_host)
        form = QFormLayout(box)

        self.unrooted_combo = self._enum_combo(UnrootedMethod)
        self.daylight_spin = QSpinBox()
        self.daylight_spin.setRange(0, 50)
        self.daylight_spin.setKeyboardTracking(False)
        self.daylight_spin.setToolTip(
            "Equal-daylight passes. Each pass costs a full sweep of the tree")

        self.unrooted_combo.currentIndexChanged.connect(
            lambda: self._param("unrooted_method",
                                self._enum_of(self.unrooted_combo,
                                              UnrootedMethod)))
        self.daylight_spin.valueChanged.connect(
            lambda v: self._param("daylight_iterations", int(v)))

        form.addRow("Method", self.unrooted_combo)
        form.addRow("Daylight passes", self.daylight_spin)
        return box

    def _build_label_group(self) -> QGroupBox:
        box = QGroupBox("Labels", self._form_host)
        form = QFormLayout(box)

        self.tip_labels_check = QCheckBox("Show tip labels")
        self.internal_labels_check = QCheckBox("Show internal labels")
        self.label_size_spin = self._spin(1.0, 96.0, 0.5, 1)
        self.internal_size_spin = self._spin(1.0, 96.0, 0.5, 1)

        self.tip_labels_check.toggled.connect(
            lambda on: self._param("show_tip_labels", bool(on)))
        self.internal_labels_check.toggled.connect(
            lambda on: self._param("show_internal_labels", bool(on)))
        self.label_size_spin.valueChanged.connect(
            lambda v: self._theme("label_size", float(v)))
        self.internal_size_spin.valueChanged.connect(
            lambda v: self._theme("internal_label_size", float(v)))

        form.addRow("", self.tip_labels_check)
        form.addRow("", self.internal_labels_check)
        form.addRow("Tip size", self.label_size_spin)
        form.addRow("Internal size", self.internal_size_spin)
        return box

    def _build_support_group(self) -> QGroupBox:
        box = QGroupBox("Support", self._form_host)
        form = QFormLayout(box)

        self.show_support_check = QCheckBox("Show support values")
        self.support_min_spin = self._spin(0.0, 1000.0, 1.0, 3, special="no floor")
        self.support_format_edit = QLineEdit()
        self.support_format_edit.setToolTip(
            "Python format specification, for example {:.3g} or {:.0f}")
        self.support_position_combo = QComboBox()
        for value, text in (("above", "Above the branch"),
                            ("below", "Below the branch"),
                            ("node", "As a sized marker")):
            self.support_position_combo.addItem(text, value)
        self.scalebar_check = QCheckBox("Show scale bar")

        self.show_support_check.toggled.connect(
            lambda on: self._theme("show_support", bool(on)))
        self.support_min_spin.valueChanged.connect(
            lambda v: self._theme("support_min", None if v <= 0.0 else float(v)))
        self.support_format_edit.editingFinished.connect(self._commit_format)
        self.support_position_combo.currentIndexChanged.connect(
            lambda: self._theme("support_position",
                                self.support_position_combo.currentData()))
        self.scalebar_check.toggled.connect(
            lambda on: self._theme("scalebar_show", bool(on)))

        form.addRow("", self.show_support_check)
        form.addRow("Threshold", self.support_min_spin)
        form.addRow("Format", self.support_format_edit)
        form.addRow("Position", self.support_position_combo)
        form.addRow("", self.scalebar_check)
        return box

    def _build_theme_group(self) -> QGroupBox:
        box = QGroupBox("Theme", self._form_host)
        form = QFormLayout(box)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.currentIndexChanged.connect(
            lambda: self.apply_theme(str(self.theme_combo.currentData())))
        form.addRow("Preset", self.theme_combo)
        return box

    def _build_selection_group(self) -> QGroupBox:
        box = QGroupBox("Selected nodes", self._form_host)
        self.selection_group = box
        form = QFormLayout(box)

        self.selection_label = QLabel("Nothing selected")
        self.branch_color_button = ColorButton()
        self.branch_width_slider = QSlider(Qt.Orientation.Horizontal)
        self.branch_width_slider.setRange(0, 200)
        self.branch_width_slider.setToolTip(
            "Branch width for the selection; 0 clears the override")
        self.branch_width_value = QLabel("inherit")
        self.label_color_button = ColorButton()
        self.bold_check = QCheckBox("Bold")
        self.italic_check = QCheckBox("Italic")
        self.clade_fill_button = ColorButton()
        self.clear_style_button = QPushButton("Clear styles")

        self.branch_color_button.colorChanged.connect(
            lambda c: self.apply_node_style("branch_color", c))
        self.branch_width_slider.valueChanged.connect(self._on_width_slider)
        self.label_color_button.colorChanged.connect(
            lambda c: self.apply_node_style("label_color", c))
        self.bold_check.toggled.connect(
            lambda on: self.apply_node_style("label_bold", bool(on) or None))
        self.italic_check.toggled.connect(
            lambda on: self.apply_node_style("label_italic", bool(on) or None))
        self.clade_fill_button.colorChanged.connect(
            lambda c: self.apply_node_style("clade_fill", c))
        self.clear_style_button.clicked.connect(self.clear_selection_style)

        width_row = QHBoxLayout()
        width_row.setContentsMargins(0, 0, 0, 0)
        width_row.addWidget(self.branch_width_slider, 1)
        width_row.addWidget(self.branch_width_value)
        width_host = QWidget()
        width_host.setLayout(width_row)

        form.addRow(self.selection_label)
        form.addRow("Branch colour", self.branch_color_button)
        form.addRow("Branch width", width_host)
        form.addRow("Label colour", self.label_color_button)
        form.addRow("", self.bold_check)
        form.addRow("", self.italic_check)
        form.addRow("Clade fill", self.clade_fill_button)
        form.addRow("", self.clear_style_button)
        return box

    # -------------------------------------------------------------- writing

    def _on_dirtied(self, _level: int) -> None:
        """Re-read the document after somebody else changed it."""
        if self._committing or self._loading:
            return
        self.reload()

    def _commit(self, fn, *args: Any, **kw: Any) -> Any:
        """Run one session mutation without letting it reload this panel.

        Reloading on the panel's own write is not merely wasteful: it rewrites
        the text of the very spin box the user is typing into, moving the caret
        under their fingers.
        """
        self._committing += 1
        try:
            return fn(*args, **kw)
        finally:
            self._committing -= 1

    def _param(self, key: str, value: Any) -> None:
        if self._loading:
            return
        self._commit(self._session.set_params, **{key: value})

    def _theme(self, key: str, value: Any) -> None:
        if self._loading:
            return
        self._commit(self._session.set_theme_attr, **{key: value})

    def _commit_format(self) -> None:
        """Validate the support format before storing it.

        A bad format string does not fail here, it fails deep inside the
        compositor on every node with a support value. Rejecting it at the point
        of entry keeps the failure attached to the thing the user just typed.
        """
        if self._loading:
            return
        text = self.support_format_edit.text().strip() or "{:.3g}"
        try:
            text.format(0.5)
        except (ValueError, IndexError, KeyError):
            self._session.statusMessage.emit(
                "Not a usable number format: %s" % text, 4000)
            self.support_format_edit.setText(self._session.theme.support_format)
            return
        self._theme("support_format", text)

    def apply_theme(self, which: str) -> None:
        """Copy a whole preset onto the document theme.

        Field by field rather than by replacing the object, because
        :attr:`Session.theme` is a live reference the canvas and every track
        already hold; swapping the object would leave them painting the old one.
        """
        if self._loading:
            return
        preset = DARK if which == "dark" else LIGHT
        values = {f.name: getattr(preset, f.name)
                  for f in dataclasses.fields(Theme)}
        self._commit(self._session.set_theme_attr, **values)

    # ------------------------------------------------------- node styling

    def apply_node_style(self, key: str, value: Any, *,
                         coalesce: bool = False) -> None:
        """Set one style key across the selection as an undoable command."""
        if self._loading:
            return
        nodes = self._session.selected_nodes()
        if not nodes:
            self._session.statusMessage.emit(
                "Select one or more nodes to style them", 3000)
            return
        self._commit(self._session.do, SetNodeStyleCommand(nodes, key, value),
                     coalesce=coalesce)

    def _on_width_slider(self, raw: int) -> None:
        """One command per drag, not one per pixel.

        ``coalesce=True`` lets the stack hand this command to the previous one's
        ``merge_with``; the merged command keeps the width from before the drag
        started, so a single undo returns to it.
        """
        width = None if raw <= 0 else raw / _WIDTH_STEPS
        self.branch_width_value.setText(
            "inherit" if width is None else format(width, ".1f"))
        self.apply_node_style("branch_width", width, coalesce=True)

    def clear_selection_style(self) -> None:
        """Drop every override this panel can set, in one history entry."""
        nodes = self._session.selected_nodes()
        if not nodes:
            return
        cmds = [SetNodeStyleCommand(nodes, k, None) for k in _STYLE_KEYS]
        self._commit(self._session.do, CompositeCommand(
            label="clear styles", commands=list(cmds),
            touches_topology=False, touches_order=False))
        self._reload_selection()

    # -------------------------------------------------------------- reading

    def reload(self) -> None:
        """Pull every control's value back out of the document."""
        self._loading = True
        try:
            p = self._session.params
            t = self._session.theme
            _select_data(self.mode_combo, LayoutMode(p.mode).value)
            _select_data(self.branch_mode_combo, BranchMode(p.branch_mode).value)
            _select_data(self.parent_rule_combo, ParentRule(p.parent_rule).value)
            self.width_spin.setValue(float(p.width))
            self.row_spacing_spin.setValue(float(p.row_spacing))
            self.x_scale_spin.setValue(0.0 if p.x_scale is None
                                       else float(p.x_scale))
            self.align_tips_check.setChecked(bool(p.align_tips))
            self.guide_lines_check.setChecked(bool(p.guide_lines))

            self.start_angle_spin.setValue(float(p.start_angle))
            self.arc_spin.setValue(float(p.arc))
            self.inner_radius_spin.setValue(float(p.inner_radius))
            _select_data(self.direction_combo, 1 if p.direction >= 0 else -1)
            self.rotate_labels_check.setChecked(bool(p.rotate_labels))

            _select_data(self.unrooted_combo,
                         UnrootedMethod(p.unrooted_method).value)
            self.daylight_spin.setValue(int(p.daylight_iterations))

            self.tip_labels_check.setChecked(bool(p.show_tip_labels))
            self.internal_labels_check.setChecked(bool(p.show_internal_labels))
            self.label_size_spin.setValue(float(t.label_size))
            self.internal_size_spin.setValue(float(t.internal_label_size))

            self.show_support_check.setChecked(bool(t.show_support))
            self.support_min_spin.setValue(0.0 if t.support_min is None
                                           else float(t.support_min))
            self.support_format_edit.setText(t.support_format)
            _select_data(self.support_position_combo, t.support_position)
            self.scalebar_check.setChecked(bool(t.scalebar_show))
            _select_data(self.theme_combo,
                         "dark" if t.name == DARK.name else "light")
        finally:
            self._loading = False
        self._reload_selection()

    def _reload_selection(self) -> None:
        """Show the styling of the selection, or disable the group."""
        nodes = self._session.selected_nodes()
        self.selection_group.setEnabled(bool(nodes))
        self._loading = True
        try:
            if not nodes:
                self.selection_label.setText("Nothing selected")
                self.branch_width_slider.setValue(0)
                self.branch_width_value.setText("inherit")
                for btn in (self.branch_color_button, self.label_color_button,
                            self.clade_fill_button):
                    btn.set_color(None)
                self.bold_check.setChecked(False)
                self.italic_check.setChecked(False)
                return
            self.selection_label.setText(
                "1 node selected" if len(nodes) == 1
                else "%d nodes selected" % len(nodes))
            style = nodes[0].style or {}
            self.branch_color_button.set_color(_as_color(style.get("branch_color")))
            self.label_color_button.set_color(_as_color(style.get("label_color")))
            self.clade_fill_button.set_color(_as_color(style.get("clade_fill")))
            width = style.get("branch_width")
            self.branch_width_slider.setValue(
                0 if width is None else int(round(float(width) * _WIDTH_STEPS)))
            self.branch_width_value.setText(
                "inherit" if width is None else format(float(width), ".1f"))
            self.bold_check.setChecked(bool(style.get("label_bold")))
            self.italic_check.setChecked(bool(style.get("label_italic")))
        finally:
            self._loading = False


def _as_color(value: Any) -> Color | None:
    return value if isinstance(value, Color) else None


def _select_data(combo: QComboBox, value: Any) -> None:
    """Select the item whose data equals *value*, leaving it alone if absent."""
    idx = combo.findData(value)
    if idx >= 0:
        combo.setCurrentIndex(idx)

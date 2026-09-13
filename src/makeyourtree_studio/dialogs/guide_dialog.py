# SPDX-License-Identifier: MIT
"""The guide, as a window: one question at a time, and a plan at the end.

Someone who does not know what figure they want will not read a manual to find
out, so this asks instead.  It is the same interview and the same recipe the
command line uses --- :mod:`makeyourtree.guide` owns both --- with the questions
drawn rather than printed.

Three things the design insists on.

**Nothing is compulsory.**  Every page has *Skip*, and *Save and close* is
available from the first page, not only at the end.  A wizard that must be
completed before it gives anything back is a wizard people abandon, and an
abandoned wizard has helped nobody.

**Work is never lost.**  The plan is written to disk when the user closes the
dialog, whatever state it is in, and reopening the file restores the answers and
continues from the first unanswered question.  Someone interrupted on Monday
comes back on Thursday to what they had.

**Measured is not chosen.**  When a published figure has been read, the answers
it produced are pre-selected *and labelled as measured*, with the evidence shown
beside them.  Presenting a measurement as the user's own choice would make the
plan's later reasoning unaccountable.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QRadioButton, QScrollArea,
                               QTextBrowser, QVBoxLayout, QWidget)

from makeyourtree.guide.figure import (FigureError, InspectorUnavailable,
                                       inspect_figure, inspector_available)
from makeyourtree.guide.plan import PLAN_EXTENSION, Plan, PlanError, load_plan, save_plan
from makeyourtree.guide.questions import Question
from makeyourtree.guide.session import GuideSession

__all__ = ["GuideDialog"]

_FIGURE_FILTER = ("Figures (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp);;"
                  "All files (*)")
_PLAN_FILTER = f"MakeYourTree plan (*{PLAN_EXTENSION});;All files (*)"


class GuideDialog(QDialog):
    """Ask, then hand over a plan."""

    def __init__(self, parent: QWidget | None = None, *,
                 session: GuideSession | None = None,
                 plan_path: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guideDialog")
        self.setWindowTitle("Guide me")
        self.setMinimumSize(620, 520)

        self._session = session or GuideSession()
        self._plan_path = plan_path
        self._plan: Plan | None = None
        self._widgets: list[Any] = []
        self._group: QButtonGroup | None = None
        self._current: Question | None = None

        self._build()
        self._show_current()

    # -------------------------------------------------------------- widgets

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        self._progress = QProgressBar()
        self._progress.setObjectName("guideProgress")
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

        self._heading = QLabel()
        self._heading.setObjectName("guideHeading")
        self._heading.setWordWrap(True)
        font = self._heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.25)
        font.setBold(True)
        self._heading.setFont(font)
        layout.addWidget(self._heading)

        self._help = QLabel()
        self._help.setObjectName("guideHelp")
        self._help.setWordWrap(True)
        self._help.setStyleSheet("color: palette(mid);")
        layout.addWidget(self._help)

        self._area = QScrollArea()
        self._area.setWidgetResizable(True)
        self._area.setFrameShape(QFrame.Shape.NoFrame)
        self._host = QWidget()
        self._choices = QVBoxLayout(self._host)
        self._choices.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._area.setWidget(self._host)
        layout.addWidget(self._area, 1)

        row = QHBoxLayout()
        self._figure_button = QPushButton("Read a published figure...")
        self._figure_button.setObjectName("guideFigureButton")
        self._figure_button.setToolTip(
            "Measure a figure from a paper to pre-fill what can be established "
            "from it. Nothing is uploaded anywhere; the measuring happens here.")
        self._figure_button.clicked.connect(self._read_figure)
        self._figure_button.setEnabled(inspector_available())
        row.addWidget(self._figure_button)
        row.addStretch(1)

        self._skip_button = QPushButton("Skip")
        self._skip_button.setObjectName("guideSkipButton")
        self._skip_button.clicked.connect(self._skip)
        row.addWidget(self._skip_button)

        self._next_button = QPushButton("Next")
        self._next_button.setObjectName("guideNextButton")
        self._next_button.setDefault(True)
        self._next_button.clicked.connect(self._advance)
        row.addWidget(self._next_button)
        layout.addLayout(row)

        buttons = QDialogButtonBox()
        self._save_button = buttons.addButton("Save and close",
                                              QDialogButtonBox.ButtonRole.AcceptRole)
        self._save_button.setObjectName("guideSaveButton")
        self._save_button.setToolTip(
            "Save what you have so far. You can reopen this and carry on.")
        cancel = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        cancel.setObjectName("guideCancelButton")
        self._save_button.clicked.connect(self._save_and_close)
        cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

    # ---------------------------------------------------------------- pages

    def _clear(self) -> None:
        self._widgets.clear()
        self._group = None
        while self._choices.count():
            item = self._choices.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_current(self) -> None:
        self._clear()
        question = self._session.next()
        self._current = question

        answered, total = self._session.progress()
        self._progress.setRange(0, total)
        self._progress.setValue(answered)
        self._progress.setFormat(f"{answered} of {total} questions")

        if question is None:
            self._show_summary()
            return

        self._heading.setText(question.text)
        self._help.setText(question.help)
        self._help.setVisible(bool(question.help))
        self._skip_button.setVisible(True)
        self._next_button.setText("Next")

        measured = question.id in self._session.measured
        existing = self._session.answers.get(question.id)

        if question.multi:
            for choice in question.choices:
                box = QCheckBox(choice.label)
                box.setToolTip(choice.detail)
                if isinstance(existing, (list, tuple)):
                    box.setChecked(choice.value in existing)
                box.setProperty("value", choice.value)
                self._choices.addWidget(box)
                if choice.detail:
                    self._choices.addWidget(self._detail(choice.detail))
                self._widgets.append(box)
        else:
            self._group = QButtonGroup(self)
            for choice in question.choices:
                button = QRadioButton(choice.label)
                button.setToolTip(choice.detail)
                button.setChecked(existing == choice.value)
                button.setProperty("value", choice.value)
                self._group.addButton(button)
                self._choices.addWidget(button)
                if choice.detail:
                    self._choices.addWidget(self._detail(choice.detail))
                self._widgets.append(button)

        if measured:
            note = QLabel(
                "Pre-filled from the figure you provided, not chosen by you. "
                "Change it if it does not match your data.")
            note.setWordWrap(True)
            note.setStyleSheet("color: palette(highlight);")
            self._choices.insertWidget(0, note)

    def _detail(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setContentsMargins(24, 0, 0, 6)
        label.setStyleSheet("color: palette(mid);")
        return label

    def _show_summary(self) -> None:
        """The finished plan, before it is saved."""
        self._plan = self._session.to_plan()
        self._heading.setText("Your plan")
        self._help.setText(
            f"{len(self._plan)} steps. Save it and work through them at your "
            f"own pace -- reopen the file any time to carry on where you left "
            f"off.")
        self._help.setVisible(True)
        self._skip_button.setVisible(False)
        self._next_button.setText("Start again")

        view = QTextBrowser()
        view.setObjectName("guidePlanView")
        view.setOpenExternalLinks(False)
        view.setMarkdown(self._plan.to_markdown())
        self._choices.addWidget(view)
        self._widgets.append(view)

    # ------------------------------------------------------- host callbacks
    #
    # The window exposes ask_open_path / ask_save_path / report_error precisely
    # so a modal file chooser can be replaced in a test. Going through them
    # rather than calling QFileDialog here is what keeps this dialog reachable
    # from the "invoke every command" test, which would otherwise block forever
    # on a native chooser with nobody to dismiss it.

    def _host(self):
        owner = self.parent()
        return owner if hasattr(owner, "ask_open_path") else None

    def _ask_open(self, caption: str, filters: str) -> str:
        host = self._host()
        if host is not None:
            return host.ask_open_path(caption, filters)
        path, _ = QFileDialog.getOpenFileName(self, caption, "", filters)
        return path

    def _ask_save(self, caption: str, suggested: str, filters: str) -> str:
        host = self._host()
        if host is not None:
            return host.ask_save_path(caption, suggested, filters)
        path, _ = QFileDialog.getSaveFileName(self, caption, suggested, filters)
        return path

    def _tell(self, title: str, message: str) -> None:
        host = self._host()
        if host is not None and hasattr(host, "report_error"):
            host.report_error(title, message)
        else:
            QMessageBox.information(self, title, message)

    # -------------------------------------------------------------- actions

    def _selected(self) -> Any:
        if self._current is None:
            return None
        if self._current.multi:
            return [w.property("value") for w in self._widgets
                    if isinstance(w, QCheckBox) and w.isChecked()]
        for widget in self._widgets:
            if isinstance(widget, QRadioButton) and widget.isChecked():
                return widget.property("value")
        return None

    def _advance(self) -> None:
        if self._current is None:
            # On the summary page this button restarts the interview, which is
            # the only way back once every question has been dealt with.
            self._session = GuideSession(tree_file=self._session.tree_file,
                                         output_stem=self._session.output_stem)
            self._plan = None
            self._show_current()
            return
        value = self._selected()
        if value in (None, [], ""):
            self._skip()
            return
        try:
            self._session.answer(self._current.id, value)
        except ValueError as exc:  # pragma: no cover - the UI limits the values
            self._tell("That answer was not understood", str(exc))
            return
        self._show_current()

    def _skip(self) -> None:
        if self._current is not None:
            self._session.skip(self._current.id)
        self._show_current()

    def _read_figure(self) -> None:
        path = self._ask_open("Read a published figure", _FIGURE_FILTER)
        if not path:
            return
        try:
            reading = inspect_figure(path)
        except InspectorUnavailable as exc:
            self._tell("Not available", str(exc))
            return
        except FigureError as exc:
            self._tell("Could not read that figure", str(exc))
            return

        taken = self._session.adopt(reading)
        body = "\n".join(f"• {line}" for line in reading.lines())
        if taken:
            body += ("\n\nPre-filled: " + ", ".join(taken) +
                     ".\nEvery one of them is a suggestion you can change.")
        else:
            body += "\n\nNothing conclusive, so every question is still open."
        self._tell("What the figure showed", body)
        self._show_current()

    # ----------------------------------------------------------------- save

    def plan(self) -> Plan:
        """The plan as it stands, finished or not."""
        return self._plan if self._plan is not None else self._session.to_plan()

    def _save_and_close(self) -> None:
        path = self._plan_path
        if not path:
            stem = self._session.output_stem or "figure"
            path = self._ask_save("Save plan", f"{stem}{PLAN_EXTENSION}",
                                  _PLAN_FILTER)
            if not path:
                return
        try:
            save_plan(self.plan(), path)
        except OSError as exc:
            self._tell("Could not save the plan", str(exc))
            return
        self._plan_path = path
        self.accept()

    @property
    def plan_path(self) -> str | None:
        return self._plan_path

    # -------------------------------------------------------------- resume

    @classmethod
    def resume(cls, parent: QWidget | None = None,
               path: str | None = None) -> "GuideDialog | None":
        """Reopen a saved plan and continue the interview.

        Returns ``None`` when the user cancels the file chooser, so a caller can
        tell "nothing to do" from "here is a dialog".
        """
        if not path:
            if parent is not None and hasattr(parent, "ask_open_path"):
                path = parent.ask_open_path("Open plan", _PLAN_FILTER)
            else:
                path, _ = QFileDialog.getOpenFileName(parent, "Open plan", "",
                                                      _PLAN_FILTER)
            if not path:
                return None
        try:
            plan = load_plan(path)
        except PlanError as exc:
            if parent is not None and hasattr(parent, "report_error"):
                parent.report_error("Could not open that plan", str(exc))
            else:
                QMessageBox.warning(parent, "Could not open that plan", str(exc))
            return None
        session = GuideSession.from_plan(plan)
        session.output_stem = os.path.splitext(os.path.basename(path))[0]
        return cls(parent, session=session, plan_path=path)

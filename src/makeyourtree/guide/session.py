# SPDX-License-Identifier: MIT
"""Driving the interview, without knowing what is asking.

The command line asks questions by printing them; the desktop wizard asks by
drawing them.  Both need the same things: what to ask next, whether an answer is
acceptable, when to stop, and how to turn the result into a plan that can be put
down and picked up days later.  Putting that here keeps the two front ends from
drifting into two subtly different interviews.

A session is *always* resumable, because it is nothing but the answers so far.
There is no hidden position to restore: :func:`~makeyourtree.guide.questions.next_question`
derives what to ask from what has been answered, so a session reconstructed from
a half-finished plan continues exactly where it stopped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .figure import FigureReading
from .plan import Plan
from .questions import Question, next_question, remaining, QUESTIONS
from .recipe import build_plan

__all__ = ["GuideSession"]


@dataclass(slots=True)
class GuideSession:
    """An interview in progress."""

    answers: dict[str, Any] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    measured: set[str] = field(default_factory=set)
    """Answers that came from inspecting a figure rather than from the user.
    Tracked so the plan can say which is which instead of crediting the user
    with a choice they never made."""
    tree_file: str = "your-tree.nwk"
    output_stem: str = "figure"
    title: str | None = None

    # ------------------------------------------------------------- lifecycle

    @classmethod
    def from_plan(cls, plan: Plan) -> "GuideSession":
        """Reopen a saved plan as an interview, to change an answer or finish.

        The answers are the durable part. Rebuilding the session from them means
        an amended answer regenerates the steps rather than leaving the plan
        describing a figure the user no longer wants.
        """
        return cls(answers=dict(plan.answers),
                   observations=list(plan.observations),
                   title=plan.title)

    def adopt(self, reading: FigureReading) -> list[str]:
        """Take what a figure inspection could establish as starting answers.

        Suggestions never overwrite something the user has already said: an
        answer they typed outranks an answer measured off someone else's
        picture.
        """
        taken: list[str] = []
        for key, value in reading.suggested.items():
            if key in self.answers:
                continue
            self.answers[key] = value
            self.measured.add(key)
            taken.append(key)
        self.observations.extend(reading.lines())
        return taken

    # -------------------------------------------------------------- progress

    def next(self) -> Question | None:
        return next_question(self.answers)

    @property
    def finished(self) -> bool:
        return self.next() is None

    def progress(self) -> tuple[int, int]:
        """(dealt with, total) over the questions that apply to this session.

        Counts what has actually been answered or skipped, rather than deriving
        it from the full bank. Some questions only appear once an earlier answer
        makes them relevant -- the label question needs a large tree, the
        colour question needs tracks -- so subtracting the applicable ones from
        the total credited the user with answering questions they had not been
        shown, and the first page read "2 of 8".

        The total therefore grows as the interview branches. That is honest: a
        bar that stays put while the end moves is less confusing than one that
        starts two-eighths full.
        """
        dealt_with = sum(1 for q in QUESTIONS if q.id in self.answers)
        return dealt_with, dealt_with + len(remaining(self.answers))

    # --------------------------------------------------------------- answers

    def answer(self, question_id: str, value: Any) -> None:
        """Record an answer, refusing one the question does not offer.

        Refusing loudly rather than storing junk: an unrecognised value would
        silently fall through every branch in the recipe and produce a plan with
        no visible connection to what the user chose.

        Answering by hand also clears any measurement for that question, so the
        plan stops crediting the figure for a choice the user has since made.
        """
        question = next((q for q in QUESTIONS if q.id == question_id), None)
        if question is None:
            raise KeyError(question_id)
        if value in (None, "", []):
            self.answers.pop(question_id, None)
            return
        if not question.accepts(value):
            allowed = ", ".join(c.value for c in question.choices)
            raise ValueError(
                f"{value!r} is not an answer to {question_id!r}; expected one "
                f"of: {allowed}")
        self.answers[question_id] = value
        self.measured.discard(question_id)

    def skip(self, question_id: str) -> None:
        """Leave a question unanswered on purpose.

        Recorded as an explicit ``None`` so the interview does not ask again,
        while the recipe still treats it as unanswered and falls back to a
        default it names. Nothing in the guide is compulsory.
        """
        self.answers[question_id] = None

    # ------------------------------------------------------------------ plan

    def to_plan(self) -> Plan:
        answers = {k: v for k, v in self.answers.items() if v not in (None, "", [])}
        return build_plan(answers,
                          observations=self.observations,
                          measured=self.measured,
                          tree_file=self.tree_file,
                          output_stem=self.output_stem,
                          title=self.title)

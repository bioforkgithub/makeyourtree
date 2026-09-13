# SPDX-License-Identifier: MIT
"""The interview: what to ask someone who does not yet know what they want.

Most people arriving with a tree do not have a figure in mind.  They have a
file, some metadata in a spreadsheet, and a destination -- a paper, a talk, a
thesis chapter.  Everything else follows from those three, so this module asks
about those and derives the rest rather than presenting a wall of options.

The design rules the question bank follows:

*Ask about the data and the destination, never about the software.*  "How many
tips does your tree have" is answerable by someone who has never opened this
program.  "Which branch mode do you want" is not, and a question the user
cannot answer is worse than no question, because they will guess.

*Every question earns its place.*  Each one changes at least one step in the
resulting plan.  A question whose answer changes nothing is a question that
wastes the goodwill needed for the next one.

*Skip what is already known.*  :func:`next_question` is given the answers so
far -- including any filled in from inspecting a published figure -- and returns
only what is still genuinely open.  Someone who uploaded a circular figure is
not asked whether they want a circular layout.

*Nothing is mandatory.*  Every question can be left unanswered, and the recipe
falls back to a defensible default and says so in the step. A wizard that
cannot be escaped is a wizard people close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

__all__ = [
    "wanted_extras",
    "Choice",
    "Question",
    "QUESTIONS",
    "question",
    "next_question",
    "remaining",
    "answered_summary",
]


@dataclass(frozen=True, slots=True)
class Choice:
    """One selectable answer."""

    value: str
    label: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Question:
    """One question, and when it applies.

    ``applies`` receives the answers gathered so far and decides whether the
    question is still worth asking.  Branching lives here rather than in the
    caller so that the CLI, the desktop wizard and a test all walk the interview
    in the same order.
    """

    id: str
    text: str
    choices: tuple[Choice, ...] = ()
    multi: bool = False
    help: str = ""
    applies: Callable[[dict[str, Any]], bool] = lambda answers: True
    free_text: bool = False

    def is_open(self, answers: dict[str, Any]) -> bool:
        """True when this has not been dealt with and still applies.

        *Present* is what counts, not *truthy*. Skipping a question stores an
        explicit ``None``, and treating that as unanswered would ask it again on
        the very next turn -- an interview the user cannot get out of except by
        answering. The recipe still sees ``None`` as "not chosen" and falls back
        to a default it names, so skipping costs nothing.
        """
        if self.id in answers:
            return False
        return bool(self.applies(answers))

    def accepts(self, value: Any) -> bool:
        """Whether *value* is a legal answer."""
        if self.free_text:
            return isinstance(value, str)
        allowed = {c.value for c in self.choices}
        if self.multi:
            return (isinstance(value, (list, tuple))
                    and all(str(v) in allowed for v in value))
        return str(value) in allowed


def _wants_tracks(answers: dict[str, Any]) -> bool:
    extras = answers.get("extra_data") or []
    return bool(extras) and "none" not in extras


def wanted_extras(answers: dict[str, Any]) -> list[str]:
    """The presentation extras asked for, expanding "as many as sensibly fit".

    Kept here beside the choices so the list cannot drift from the question:
    adding a choice above without adding it to the expansion would make
    "everything" quietly mean "everything except the new one".
    """
    chosen = list(answers.get("extras") or [])
    if "none" in chosen:
        return []
    if "everything" in chosen:
        return ["support", "scale_bar", "collapse", "guides", "symbols",
                "legend"]
    return [c for c in chosen if c != "everything"]


def _large(answers: dict[str, Any]) -> bool:
    return answers.get("tip_count") in {"hundreds", "thousands"}


#: The bank, in the order it is asked.
QUESTIONS: tuple[Question, ...] = (
    Question(
        id="goal",
        text="What is this figure for?",
        help="This sets the size, the resolution and the file format at the "
             "end, so the figure comes out fit for where it is going.",
        choices=(
            Choice("paper", "A journal article",
                   "Vector PDF, sized to a journal column."),
            Choice("thesis", "A thesis or report",
                   "Vector PDF at page width."),
            Choice("talk", "A talk or slides",
                   "PNG at screen resolution, larger text."),
            Choice("poster", "A poster",
                   "High-resolution PNG or vector PDF, printed large."),
            Choice("explore", "Just looking at the data",
                   "Fast on-screen exploration; no export step."),
        ),
    ),
    Question(
        id="tip_count",
        text="Roughly how many tips does your tree have?",
        help="The single strongest constraint on the layout. Labels that fit "
             "at 30 tips are unreadable at 3000.",
        choices=(
            Choice("tens", "Up to about 50"),
            Choice("hundreds", "50 to a few hundred"),
            Choice("thousands", "More than a thousand"),
            Choice("unknown", "I do not know",
                   "The plan will start with a step that tells you."),
        ),
    ),
    Question(
        id="branch_meaning",
        text="Do the branch lengths in your file mean something?",
        help="A phylogram draws them to scale and claims they are meaningful. "
             "A cladogram shows only the branching order. Readers cannot tell "
             "which they are looking at unless you say so.",
        choices=(
            Choice("substitutions", "Yes -- substitutions or distance"),
            Choice("time", "Yes -- time, a dated tree"),
            Choice("meaningless", "No, or I do not trust them",
                   "A cladogram is the honest choice."),
            Choice("absent", "My file has no branch lengths"),
            Choice("unsure", "I am not sure",
                   "The plan will include a step to check."),
        ),
    ),
    Question(
        id="rooting",
        text="How should the tree be rooted?",
        help="Where the root sits decides which groups look monophyletic. It "
             "is the choice most likely to change what a reader concludes.",
        choices=(
            Choice("outgroup", "I have an outgroup",
                   "The best option: it encodes a real hypothesis."),
            Choice("already", "It is already rooted correctly"),
            Choice("midpoint", "Use the midpoint",
                   "Reasonable with no outgroup; assumes similar rates."),
            Choice("unrooted", "Show it unrooted",
                   "Makes no claim about ancestry."),
            Choice("unsure", "I do not know"),
        ),
    ),
    Question(
        id="extra_data",
        text="What else do you want to show beside the tree?",
        help="Choose everything that applies. Each becomes an annotation "
             "track, and the plan will tell you what file to prepare.",
        multi=True,
        choices=(
            Choice("category", "A category per tip",
                   "Host, region, lineage, treatment group."),
            Choice("value", "One number per tip",
                   "Body mass, titre, branch support, count."),
            Choice("matrix", "A matrix of numbers",
                   "Expression across conditions, abundance across samples."),
            Choice("presence", "Presence or absence of features",
                   "Genes, resistances, traits."),
            Choice("composition", "Proportions that add to a whole",
                   "Read shares, population composition."),
            Choice("series", "A short series per tip",
                   "A time course or profile."),
            Choice("domains", "Protein domain architecture"),
            Choice("links", "Relationships between tips",
                   "Transfer, recombination, host jumps."),
            Choice("highlight", "Named, highlighted clades"),
            Choice("none", "Nothing -- just the tree"),
        ),
    ),
    Question(
        id="extras",
        text="Do you want any extra features on the figure?",
        help="These are presentation rather than data, and they combine "
             "freely -- pick as many as you like. If you are not sure, take "
             "the last option and see what the tool can do.",
        multi=True,
        choices=(
            Choice("support", "Branch support values",
                   "Bootstrap or posterior probabilities shown at the nodes."),
            Choice("scale_bar", "A scale bar",
                   "What one unit of branch length means."),
            Choice("collapse", "Collapsed clades",
                   "Fold away the groups you are not discussing."),
            Choice("guides", "Guide lines from the tips to their labels",
                   "Makes each row easy to follow across to its data."),
            Choice("symbols", "Symbols marking particular nodes",
                   "Sized or coloured by a value of your choosing."),
            Choice("legend", "A legend for every track"),
            Choice("dark", "A dark background",
                   "Good for slides; check your journal accepts it."),
            Choice("everything", "As many as sensibly fit",
                   "Combine the lot. The plan will say where they stop "
                   "helping."),
            Choice("none", "None of these"),
        ),
    ),
    Question(
        id="label_tips",
        text="Should every tip be labelled?",
        applies=_large,
        help="You said the tree is large. Thousands of tip labels cannot be "
             "read at any printable size, and usually the clades are the point.",
        choices=(
            Choice("all", "Yes, label them all"),
            Choice("none", "No labels",
                   "Recommended above a few hundred tips."),
            Choice("some", "Only the ones that matter",
                   "Label a few by hand; collapse the rest."),
        ),
    ),
    Question(
        id="shape",
        text="Do you have a shape in mind?",
        help="If not, say so -- the plan will recommend one from your answers "
             "and explain why.",
        choices=(
            Choice("rectangular", "Rectangular", "The familiar default."),
            Choice("circular", "Circular fan",
                   "Fits a large tree into a square; good with rings of data."),
            Choice("unrooted", "Unrooted"),
            Choice("recommend", "Recommend one for me"),
        ),
    ),
    Question(
        id="colour_safe",
        text="Should the colours be safe for colour-vision deficiency?",
        applies=_wants_tracks,
        help="Roughly 1 in 12 men cannot reliably distinguish red from green. "
             "Several journals now require this.",
        choices=(
            Choice("yes", "Yes", "Use a colour-vision-safe palette."),
            Choice("no", "No, I have my own colours"),
        ),
    ),
)


def question(question_id: str) -> Question:
    for item in QUESTIONS:
        if item.id == question_id:
            return item
    raise KeyError(question_id)


def next_question(answers: dict[str, Any]) -> Question | None:
    """The next question worth asking, or ``None`` when the interview is done."""
    for item in QUESTIONS:
        if item.is_open(answers):
            return item
    return None


def remaining(answers: dict[str, Any]) -> tuple[Question, ...]:
    """Every question still open, for a progress indicator."""
    return tuple(item for item in QUESTIONS if item.is_open(answers))


def answered_summary(answers: dict[str, Any]) -> list[str]:
    """Human-readable echo of what was chosen, for the plan and for review."""
    lines: list[str] = []
    for item in QUESTIONS:
        if item.id not in answers:
            continue
        value = answers[item.id]
        if value in (None, "", []):
            continue
        labels = {c.value: c.label for c in item.choices}
        if isinstance(value, (list, tuple)):
            shown = ", ".join(labels.get(str(v), str(v)) for v in value)
        else:
            shown = labels.get(str(value), str(value))
        lines.append(f"{item.text} {shown}")
    return lines

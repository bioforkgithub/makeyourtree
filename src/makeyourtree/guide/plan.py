# SPDX-License-Identifier: MIT
"""A plan: the steps to make one figure, and where the user got to.

The unit of work here is a *plan*, saved as ``.myplan``.  It holds the answers
that produced it, the observations behind those answers, the ordered steps, and
which steps are done.  That last part is the whole point: someone starts a
figure on Monday, is interrupted, and comes back on Thursday having forgotten
what they had decided.  A plan that records only the steps would make them
re-derive their own choices; a plan that records the answers as well can be
re-generated, amended, or simply read back.

Three properties the format is built around.

*Plain JSON, and readable.*  A plan is a working document.  Someone will open it
in a text editor, send it to a supervisor, or paste a step into a terminal, so
it is indented JSON with ordinary words for keys rather than a packed binary.

*Forward compatible.*  Unknown keys are preserved through a load-and-save cycle.
A plan written by a later version keeps whatever this one does not understand,
because silently dropping a field is how a user loses work they cannot see.

*No clock surprises.*  Timestamps are ISO-8601 UTC.  A plan moved between
machines in different time zones must not appear to have been edited in the
future.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

__all__ = [
    "PLAN_FORMAT",
    "PLAN_VERSION",
    "PLAN_EXTENSION",
    "PlanError",
    "Step",
    "Plan",
    "save_plan",
    "load_plan",
]

PLAN_FORMAT = "makeyourtree-plan"
PLAN_VERSION = 1
PLAN_EXTENSION = ".myplan"

#: Keys the loader understands. Anything else is carried in ``Plan.unknown``.
_KNOWN_PLAN_KEYS = frozenset({
    "format", "version", "title", "created", "updated", "answers",
    "observations", "steps", "notes",
})
_KNOWN_STEP_KEYS = frozenset({
    "id", "title", "detail", "command", "done", "note", "optional",
})


class PlanError(ValueError):
    """A plan file could not be read."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class Step:
    """One thing to do, in order.

    ``command`` is a shell command the user can paste verbatim when the step has
    one.  Not every step does -- "decide whether your branch lengths mean
    anything" is a judgement, not a command -- and inventing a command for those
    would be worse than leaving the field empty.
    """

    id: str
    title: str
    detail: str = ""
    command: str = ""
    done: bool = False
    note: str = ""
    optional: bool = False
    unknown: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = dict(self.unknown)
        data.update({
            "id": self.id,
            "title": self.title,
            "detail": self.detail,
            "command": self.command,
            "done": self.done,
            "note": self.note,
            "optional": self.optional,
        })
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Step":
        if not isinstance(data, dict):
            raise PlanError(f"a step must be an object, got {type(data).__name__}")
        step_id = str(data.get("id") or "")
        if not step_id:
            raise PlanError("every step needs an id")
        return cls(
            id=step_id,
            title=str(data.get("title") or ""),
            detail=str(data.get("detail") or ""),
            command=str(data.get("command") or ""),
            done=bool(data.get("done", False)),
            note=str(data.get("note") or ""),
            optional=bool(data.get("optional", False)),
            unknown={k: v for k, v in data.items() if k not in _KNOWN_STEP_KEYS},
        )


@dataclass(slots=True)
class Plan:
    """An ordered list of steps, plus everything needed to rebuild them."""

    title: str = "Untitled figure"
    steps: list[Step] = field(default_factory=list)
    answers: dict[str, Any] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    notes: str = ""
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    unknown: dict[str, Any] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------- progress

    def __iter__(self) -> Iterator[Step]:
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    @property
    def done_count(self) -> int:
        return sum(1 for step in self.steps if step.done)

    @property
    def is_complete(self) -> bool:
        """Every step that is not optional has been done."""
        return all(step.done or step.optional for step in self.steps)

    def next_step(self) -> Step | None:
        """The first step still to do, or ``None`` when the plan is finished.

        This is what "resume" means: the plan does not track a cursor that could
        drift out of step with the flags, it derives the position from the work
        itself.
        """
        for step in self.steps:
            if not step.done:
                return step
        return None

    def step(self, step_id: str) -> Step:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)

    def mark(self, step_id: str, done: bool = True, note: str | None = None) -> Step:
        """Tick a step off (or un-tick it), and stamp the plan as touched."""
        step = self.step(step_id)
        step.done = bool(done)
        if note is not None:
            step.note = note
        self.updated = _now()
        return step

    def progress(self) -> str:
        """A one-line summary for a status bar or a terminal."""
        total = len(self.steps)
        if total == 0:
            return "no steps"
        return f"{self.done_count} of {total} steps done"

    # ---------------------------------------------------------- conversion

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = dict(self.unknown)
        data.update({
            "format": PLAN_FORMAT,
            "version": PLAN_VERSION,
            "title": self.title,
            "created": self.created,
            "updated": self.updated,
            "answers": copy.deepcopy(self.answers),
            "observations": list(self.observations),
            "notes": self.notes,
            "steps": [step.to_json() for step in self.steps],
        })
        return data

    @classmethod
    def from_json(cls, data: Any) -> "Plan":
        if not isinstance(data, dict):
            raise PlanError("a plan file must contain a JSON object")
        fmt = data.get("format")
        if fmt != PLAN_FORMAT:
            raise PlanError(
                f"not a MakeYourTree plan: expected format {PLAN_FORMAT!r}, "
                f"found {fmt!r}")
        version = data.get("version")
        if isinstance(version, int) and version > PLAN_VERSION:
            raise PlanError(
                f"this plan was written by a newer version of MakeYourTree "
                f"(plan version {version}, this build reads {PLAN_VERSION}). "
                f"Upgrade rather than risk losing what it contains.")
        raw_steps = data.get("steps") or []
        if not isinstance(raw_steps, list):
            raise PlanError("'steps' must be a list")
        answers = data.get("answers") or {}
        if not isinstance(answers, dict):
            raise PlanError("'answers' must be an object")
        return cls(
            title=str(data.get("title") or "Untitled figure"),
            steps=[Step.from_json(item) for item in raw_steps],
            answers=dict(answers),
            observations=[str(o) for o in (data.get("observations") or [])],
            notes=str(data.get("notes") or ""),
            created=str(data.get("created") or _now()),
            updated=str(data.get("updated") or _now()),
            unknown={k: v for k, v in data.items() if k not in _KNOWN_PLAN_KEYS},
        )

    # -------------------------------------------------------------- export

    def to_markdown(self) -> str:
        """The plan as a checklist someone can print, email or commit.

        Markdown rather than plain text because the checkbox syntax renders as a
        real checklist on GitHub and in most editors, which is what makes it
        usable as a working document away from the application.
        """
        lines = [f"# {self.title}", "",
                 f"*{self.progress()}. Last updated {self.updated}.*", ""]
        if self.observations:
            lines += ["## What this was based on", ""]
            lines += [f"- {text}" for text in self.observations]
            lines.append("")
        lines += ["## Steps", ""]
        for index, step in enumerate(self.steps, start=1):
            box = "x" if step.done else " "
            suffix = "  *(optional)*" if step.optional else ""
            lines.append(f"{index}. [{box}] **{step.title}**{suffix}")
            if step.detail:
                lines += ["", *_continued(step.detail)]
            if step.command:
                lines += ["", "   ```bash", f"   {step.command}", "   ```"]
            if step.note:
                lines += ["", *_continued(step.note, first="> Note: ", rest="> ")]
            lines.append("")
        if self.notes:
            lines += ["## Notes", "", self.notes, ""]
        return "\n".join(lines).rstrip() + "\n"


def _continued(text: str, first: str = "", rest: str = "") -> list[str]:
    """Indent every line of *text* to sit inside a numbered list item.

    A step's detail can carry more than one line -- the interview joins the
    layout reason and the branch-mode reason with a newline.  Indenting only
    the first, as a single f-string does, drops the rest to column zero, which
    closes the list and restarts the numbering in every Markdown renderer.

    *first* and *rest* differ because a blockquote continues with a bare ``>``:
    repeating the whole "> Note:" label on each line would read as several
    separate notes.
    """
    out: list[str] = []
    for index, line in enumerate(text.splitlines()):
        if not line:
            out.append("")
            continue
        out.append(f"   {first if index == 0 else rest}{line}")
    return out


def save_plan(plan: Plan, path: str | os.PathLike[str]) -> None:
    """Write *plan* to *path*.

    Written to a neighbouring temporary file and moved into place, so an
    interrupted save cannot leave a half-written plan where the user's work
    used to be.
    """
    plan.updated = _now()
    target = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(target))
    temporary = os.path.join(directory, f".{os.path.basename(target)}.tmp")
    payload = json.dumps(plan.to_json(), indent=2, ensure_ascii=False)
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")
    os.replace(temporary, target)


def load_plan(path: str | os.PathLike[str]) -> Plan:
    """Read a plan, with a message a user can act on when it is not one."""
    target = os.fspath(path)
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise PlanError(f"no plan at {target}") from None
    except json.JSONDecodeError as exc:
        raise PlanError(f"{target} is not valid JSON: {exc}") from None
    return Plan.from_json(data)

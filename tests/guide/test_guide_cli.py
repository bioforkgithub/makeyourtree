# SPDX-License-Identifier: MIT
"""``makeyourtree guide`` and ``makeyourtree plan`` from the outside.

The interview is interactive, so these drive it by feeding stdin. The case worth
the most attention is the one nobody tests by hand: pressing Enter at every
prompt. A question that is asked again after being skipped makes an interview
the user cannot escape, and that is exactly the shape of bug an automated run
catches and a manual one does not.
"""

from __future__ import annotations

import io
import json

import pytest

from makeyourtree.cli import main
from makeyourtree.guide.plan import load_plan


def run(capsys, *argv, stdin: str = ""):
    import sys

    saved = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        code = main(list(argv))
    finally:
        sys.stdin = saved
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def plan_path(tmp_path):
    return tmp_path / "figure.myplan"


# -------------------------------------------------------------------- guide


def test_yes_produces_a_plan_without_asking(capsys, plan_path):
    code, out, _ = run(capsys, "guide", "--yes", "--output", str(plan_path))
    assert code == 0
    assert plan_path.is_file()
    assert "Resume any time" in out
    assert len(load_plan(plan_path)) >= 3


def test_an_interview_produces_a_plan_shaped_by_the_answers(capsys, plan_path):
    # goal=paper, tips=tens, lengths=substitutions, rooting=outgroup,
    # extras=category, shape=recommend, colour-safe=yes
    code, _, _ = run(capsys, "guide", "--tree", "mine.nwk", "--name", "fig",
                     "--output", str(plan_path),
                     stdin="1\n1\n1\n1\n1\n4\n1\n")
    assert code == 0
    plan = load_plan(plan_path)
    assert plan.answers["goal"] == "paper"
    assert plan.answers["extra_data"] == ["category"]
    assert "mine.nwk" in plan.step("inspect").command
    assert "fig.pdf" in plan.step("render").command


def test_skipping_every_question_terminates(capsys, plan_path):
    """The interview must be escapable by pressing Enter, not only by answering."""
    code, _, _ = run(capsys, "guide", "--output", str(plan_path),
                     stdin="\n" * 20)
    assert code == 0
    plan = load_plan(plan_path)
    assert len(plan) >= 2, "a plan with no answers is still a place to start"


def test_quitting_keeps_what_was_answered(capsys, plan_path):
    code, out, _ = run(capsys, "guide", "--output", str(plan_path), stdin="1\nq\n")
    assert code == 0
    assert "kept" in out
    assert load_plan(plan_path).answers.get("goal") == "paper"


def test_a_closed_stdin_does_not_crash(capsys, plan_path):
    """Piping from a file that runs out must end the interview, not raise."""
    code, _, _ = run(capsys, "guide", "--output", str(plan_path), stdin="")
    assert code == 0
    assert plan_path.is_file()


def test_an_unrecognised_answer_re_asks(capsys, plan_path):
    code, _, err = run(capsys, "guide", "--output", str(plan_path),
                       stdin="banana\n1\nq\n")
    assert code == 0
    assert "did not recognise" in err
    assert load_plan(plan_path).answers.get("goal") == "paper"


def test_a_missing_figure_is_reported(capsys, plan_path, tmp_path):
    code, _, err = run(capsys, "guide", "--from-figure",
                       str(tmp_path / "absent.pdf"),
                       "--output", str(plan_path), "--yes")
    assert code != 0
    assert "Traceback" not in err


# --------------------------------------------------------------------- plan


@pytest.fixture
def saved(capsys, plan_path):
    run(capsys, "guide", "--yes", "--output", str(plan_path))
    return plan_path


def test_plan_shows_what_is_next(capsys, saved):
    code, out, _ = run(capsys, "plan", str(saved))
    assert code == 0
    assert "Next:" in out and "steps done" in out


def test_a_step_can_be_ticked_off_by_number(capsys, saved):
    code, _, _ = run(capsys, "plan", str(saved), "--done", "1")
    assert code == 0
    assert load_plan(saved).steps[0].done


def test_a_step_can_be_ticked_off_by_id(capsys, saved):
    run(capsys, "plan", str(saved), "--done", "inspect")
    assert load_plan(saved).step("inspect").done


def test_a_note_is_kept_with_the_step(capsys, saved):
    run(capsys, "plan", str(saved), "--done", "inspect", "--note", "412 tips")
    assert load_plan(saved).step("inspect").note == "412 tips"


def test_progress_survives_between_runs(capsys, saved):
    """The whole point: stop, come back, carry on."""
    run(capsys, "plan", str(saved), "--done", "1")
    code, out, _ = run(capsys, "plan", str(saved))
    assert code == 0
    assert "1 of" in out
    assert load_plan(saved).next_step().id != load_plan(saved).steps[0].id


def test_a_step_can_be_un_ticked(capsys, saved):
    run(capsys, "plan", str(saved), "--done", "1")
    run(capsys, "plan", str(saved), "--undo", "1")
    assert not load_plan(saved).steps[0].done


def test_export_writes_a_markdown_checklist(capsys, saved, tmp_path):
    target = tmp_path / "plan.md"
    code, _, _ = run(capsys, "plan", str(saved), "--export", str(target))
    assert code == 0
    text = target.read_text(encoding="utf-8")
    assert text.startswith("#") and "[ ]" in text


def test_an_unknown_step_is_refused(capsys, saved):
    code, _, err = run(capsys, "plan", str(saved), "--done", "nonexistent")
    assert code != 0
    assert "no step" in err and "Traceback" not in err


def test_a_missing_plan_is_a_message(capsys, tmp_path):
    code, _, err = run(capsys, "plan", str(tmp_path / "absent.myplan"))
    assert code != 0
    assert "Traceback" not in err


def test_a_finished_plan_says_so(capsys, saved):
    plan = load_plan(saved)
    for step in plan.steps:
        run(capsys, "plan", str(saved), "--done", step.id)
    code, out, _ = run(capsys, "plan", str(saved))
    assert code == 0
    assert "Every step is done" in out

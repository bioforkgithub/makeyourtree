# SPDX-License-Identifier: MIT
"""Plans, and the promise that work survives being put down.

The feature this file guards is "stop on Monday, resume on Thursday". Anything
that loses an answer, forgets which steps were done, or refuses to read a plan
it wrote is a bug that costs a user real work, so the round trip is checked
harder than anything else here.
"""

from __future__ import annotations

import json

import pytest

from makeyourtree.guide.plan import (PLAN_FORMAT, PLAN_VERSION, Plan, PlanError,
                                     Step, load_plan, save_plan)


@pytest.fixture
def plan() -> Plan:
    return Plan(
        title="A figure",
        steps=[Step("one", "First", detail="do this", command="echo 1"),
               Step("two", "Second"),
               Step("three", "Third", optional=True)],
        answers={"goal": "paper", "extra_data": ["category"]},
        observations=["measured something"],
    )


# ------------------------------------------------------------------ progress


def test_a_new_plan_starts_at_the_first_step(plan):
    assert plan.next_step().id == "one"
    assert plan.done_count == 0


def test_marking_a_step_advances_the_resume_point(plan):
    plan.mark("one")
    assert plan.next_step().id == "two"
    assert plan.done_count == 1


def test_a_step_can_be_un_marked(plan):
    plan.mark("one")
    plan.mark("one", done=False)
    assert plan.next_step().id == "one"


def test_the_resume_point_is_derived_not_stored(plan):
    """Marking out of order must not strand the user mid-plan.

    The position comes from the flags rather than a cursor, so a plan can be
    worked through in any order and still knows what is left.
    """
    plan.mark("two")
    assert plan.next_step().id == "one"
    plan.mark("one")
    assert plan.next_step().id == "three"


def test_optional_steps_do_not_block_completion(plan):
    plan.mark("one")
    plan.mark("two")
    assert plan.is_complete
    assert plan.next_step().id == "three", "still offered, just not required"


def test_marking_stamps_the_plan_as_touched(plan):
    before = plan.updated
    plan.updated = "2000-01-01T00:00:00+00:00"
    plan.mark("one")
    assert plan.updated != "2000-01-01T00:00:00+00:00"


def test_progress_reads_like_a_sentence(plan):
    assert plan.progress() == "0 of 3 steps done"


def test_marking_an_unknown_step_is_an_error(plan):
    with pytest.raises(KeyError):
        plan.mark("nonexistent")


# -------------------------------------------------------------- round trips


def test_a_plan_survives_a_save_and_load(plan, tmp_path):
    plan.mark("one", note="went fine")
    path = tmp_path / "p.myplan"
    save_plan(plan, path)
    again = load_plan(path)

    assert again.title == plan.title
    assert again.answers == plan.answers
    assert again.observations == plan.observations
    assert [s.id for s in again.steps] == ["one", "two", "three"]
    assert again.step("one").done and again.step("one").note == "went fine"
    assert again.step("three").optional
    assert again.next_step().id == "two", "resumes where it stopped"


def test_the_file_is_readable_json(plan, tmp_path):
    """People will open this in an editor, and should be able to."""
    path = tmp_path / "p.myplan"
    save_plan(plan, path)
    text = path.read_text(encoding="utf-8")
    assert "\n  " in text, "indented, not packed onto one line"
    data = json.loads(text)
    assert data["format"] == PLAN_FORMAT
    assert data["version"] == PLAN_VERSION


def test_unknown_fields_survive_a_round_trip(tmp_path):
    """A plan written by a later version must not lose what this one cannot read."""
    path = tmp_path / "future.myplan"
    path.write_text(json.dumps({
        "format": PLAN_FORMAT,
        "version": PLAN_VERSION,
        "title": "From the future",
        "steps": [{"id": "a", "title": "A", "mood": "cheerful"}],
        "weather": "fine",
    }), encoding="utf-8")

    plan = load_plan(path)
    save_plan(plan, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["weather"] == "fine"
    assert data["steps"][0]["mood"] == "cheerful"


def test_a_save_never_leaves_a_half_written_plan(plan, tmp_path, monkeypatch):
    """The user's previous plan must survive a failed write."""
    path = tmp_path / "p.myplan"
    save_plan(plan, path)
    original = path.read_bytes()

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", explode)
    with pytest.raises(OSError):
        save_plan(plan, path)
    assert path.read_bytes() == original


# ------------------------------------------------------------------- errors


def test_a_missing_plan_says_so(tmp_path):
    with pytest.raises(PlanError, match="no plan at"):
        load_plan(tmp_path / "absent.myplan")


def test_broken_json_names_the_file(tmp_path):
    path = tmp_path / "bad.myplan"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(PlanError, match="not valid JSON"):
        load_plan(path)


def test_another_kind_of_json_is_refused(tmp_path):
    path = tmp_path / "other.myplan"
    path.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
    with pytest.raises(PlanError, match="not a MakeYourTree plan"):
        load_plan(path)


def test_a_newer_plan_version_refuses_rather_than_guesses(tmp_path):
    """Reading a future format half-correctly would silently discard work."""
    path = tmp_path / "newer.myplan"
    path.write_text(json.dumps({"format": PLAN_FORMAT,
                                "version": PLAN_VERSION + 5,
                                "steps": []}), encoding="utf-8")
    with pytest.raises(PlanError, match="newer version"):
        load_plan(path)


def test_a_step_without_an_id_is_refused(tmp_path):
    path = tmp_path / "noid.myplan"
    path.write_text(json.dumps({"format": PLAN_FORMAT, "version": 1,
                                "steps": [{"title": "nameless"}]}),
                    encoding="utf-8")
    with pytest.raises(PlanError, match="id"):
        load_plan(path)


# ------------------------------------------------------------------ markdown


def test_markdown_export_is_a_real_checklist(plan):
    plan.mark("one")
    text = plan.to_markdown()
    assert "# A figure" in text
    assert "1. [x] **First**" in text
    assert "2. [ ] **Second**" in text
    assert "*(optional)*" in text
    assert "```bash" in text and "echo 1" in text


def test_markdown_records_what_the_plan_was_based_on(plan):
    assert "measured something" in plan.to_markdown()


def test_markdown_indents_every_line_of_a_multi_line_detail():
    """A second line at column zero closes the list and restarts the numbering."""
    plan = Plan(title="A figure",
                steps=[Step("one", "First", detail="First line.\nSecond line."),
                       Step("two", "Second")])
    text = plan.to_markdown()
    assert "\n   First line.\n   Second line.\n" in text
    assert "\nSecond line." not in text
    # The list survives: the second item is still numbered as an item.
    assert "2. [ ] **Second**" in text


def test_markdown_indents_every_line_of_a_multi_line_note():
    plan = Plan(title="A figure",
                steps=[Step("one", "First", note="Watch out.\nSeriously.")])
    text = plan.to_markdown()
    assert "\n   > Note: Watch out.\n   > Seriously.\n" in text

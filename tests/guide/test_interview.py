# SPDX-License-Identifier: MIT
"""The interview, the recipe it produces, and reading a figure.

Two things are being protected. First, that the questions branch on the answers
rather than being a fixed list, because asking someone with 20 tips whether to
drop the labels wastes the attention needed for the questions that matter.
Second, that the plan never claims the user said something they did not -- an
answer measured off a picture must be labelled as measured.
"""

from __future__ import annotations

import numpy as np
import pytest

from makeyourtree.guide.figure import (FigureError, FigureReading,
                                       InspectorUnavailable, Observation,
                                       inspect_figure)
from makeyourtree.guide.questions import QUESTIONS, next_question, question
from makeyourtree.guide.recipe import build_plan, recommend_layout
from makeyourtree.guide.session import GuideSession


# ----------------------------------------------------------------- questions


def test_the_interview_starts_somewhere_and_ends():
    assert next_question({}) is not None
    answered = {q.id: (q.choices[0].value if not q.multi
                       else [q.choices[0].value]) for q in QUESTIONS}
    assert next_question(answered) is None


def test_every_question_has_answerable_choices():
    """A question the user cannot answer is worse than no question."""
    for item in QUESTIONS:
        assert item.text.endswith("?"), item.id
        assert item.choices, item.id
        assert len({c.value for c in item.choices}) == len(item.choices)


def test_label_question_is_only_asked_for_a_big_tree():
    """Nobody with 20 tips needs to be asked whether to drop the labels."""
    small = {"tip_count": "tens"}
    large = {"tip_count": "thousands"}
    assert not question("label_tips").is_open(small)
    assert question("label_tips").is_open(large)


def test_colour_question_is_only_asked_when_there_is_colour():
    assert not question("colour_safe").is_open({"extra_data": ["none"]})
    assert question("colour_safe").is_open({"extra_data": ["category"]})


def test_an_answered_question_is_not_asked_again():
    assert not question("goal").is_open({"goal": "paper"})


def test_a_skipped_question_is_not_asked_again():
    """Skipping is a decision, and re-asking would punish it."""
    assert not question("goal").is_open({"goal": None})


# ------------------------------------------------------------------- session


def test_answers_are_validated():
    session = GuideSession()
    with pytest.raises(ValueError, match="not an answer"):
        session.answer("goal", "sideways")


def test_an_unknown_question_is_an_error():
    with pytest.raises(KeyError):
        GuideSession().answer("favourite_colour", "blue")


def test_a_session_is_just_its_answers():
    """Which is what makes resuming free rather than a restored cursor."""
    session = GuideSession()
    session.answer("goal", "paper")
    resumed = GuideSession(answers=dict(session.answers))
    assert resumed.next().id == next_question(session.answers).id


def test_a_plan_reopens_as_an_interview():
    session = GuideSession()
    session.answer("goal", "talk")
    plan = session.to_plan()
    again = GuideSession.from_plan(plan)
    assert again.answers["goal"] == "talk"


def test_measured_answers_are_not_credited_to_the_user():
    reading = FigureReading(suggested={"shape": "circular"})
    session = GuideSession()
    session.adopt(reading)
    _, why = recommend_layout(session.answers, session.measured)
    assert "Measured from the figure" in why
    assert "You asked" not in why


def test_answering_by_hand_overrides_a_measurement():
    reading = FigureReading(suggested={"shape": "circular"})
    session = GuideSession()
    session.adopt(reading)
    session.answer("shape", "rectangular")
    assert session.answers["shape"] == "rectangular"
    _, why = recommend_layout(session.answers, session.measured)
    assert "You asked for this shape." == why


def test_a_measurement_never_overwrites_the_user():
    session = GuideSession()
    session.answer("shape", "rectangular")
    session.adopt(FigureReading(suggested={"shape": "circular"}))
    assert session.answers["shape"] == "rectangular"


# -------------------------------------------------------------------- recipe


def test_a_plan_is_produced_from_nothing_at_all():
    """Someone who answers no questions must still get somewhere to start."""
    plan = build_plan({})
    assert len(plan) >= 3
    assert plan.steps[0].command.startswith("makeyourtree info")


def test_the_render_step_carries_a_runnable_command():
    plan = build_plan({"goal": "paper", "extra_data": ["category"]},
                      tree_file="mine.nwk", output_stem="fig")
    render = plan.step("render")
    assert render.command.startswith("makeyourtree render")
    assert "fig.pdf" in render.command
    assert "--track category.mytrack" in render.command


def test_rooting_choice_changes_the_command_and_the_input_file():
    outgroup = build_plan({"rooting": "outgroup"}, tree_file="t.nwk")
    assert "--outgroup" in outgroup.step("root").command
    assert "rooted.nwk" in outgroup.step("render").command

    already = build_plan({"rooting": "already"}, tree_file="t.nwk")
    with pytest.raises(KeyError):
        already.step("root")
    assert "t.nwk" in already.step("render").command


def test_meaningless_branch_lengths_produce_a_cladogram():
    plan = build_plan({"branch_meaning": "meaningless"})
    assert "cladogram" in plan.step("render").command


def test_each_kind_of_data_becomes_its_own_step():
    plan = build_plan({"extra_data": ["category", "matrix", "presence"]})
    for key in ("data-category", "data-matrix", "data-presence"):
        plan.step(key)


@pytest.mark.parametrize("answers,expected", [
    ({"tip_count": "tens"}, "rectangular"),
    ({"tip_count": "thousands"}, "circular"),
    ({"rooting": "unrooted"}, "unrooted"),
    ({"tip_count": "hundreds", "extra_data": ["category", "matrix"]}, "circular"),
])
def test_layout_recommendation_follows_the_data(answers, expected):
    mode, why = recommend_layout(answers)
    assert mode == expected
    assert why, "a recommendation without a reason cannot be judged"


def test_the_destination_sets_the_format():
    assert ".pdf" in build_plan({"goal": "paper"}).step("render").command
    assert ".png" in build_plan({"goal": "talk"}).step("render").command
    assert "--dpi" in build_plan({"goal": "poster"}).step("render").command


def test_a_plan_records_what_it_was_based_on():
    plan = build_plan({"goal": "paper"}, observations=["a figure said so"])
    assert "a figure said so" in plan.observations
    assert any("journal" in o.lower() for o in plan.observations)


# -------------------------------------------------------------- figure input


def test_a_missing_figure_is_a_message_not_a_traceback(tmp_path):
    with pytest.raises(FigureError, match="no such file"):
        inspect_figure(tmp_path / "absent.pdf")


def test_an_observation_states_its_confidence():
    assert "likely" in str(Observation("k", "s", "because", 0.9))
    assert "uncertain" in str(Observation("k", "s", "because", 0.1))


def test_a_reading_reports_what_it_measured():
    reading = FigureReading(source="/tmp/paper.pdf",
                            observations=[Observation("shape", "A fan", "round")])
    lines = reading.lines()
    assert any("paper.pdf" in line for line in lines)
    assert any("A fan" in line for line in lines)


class TestQtInspector:
    """The measuring itself, which needs the desktop extra."""

    @pytest.fixture(autouse=True)
    def _needs_qt(self):
        pytest.importorskip("PySide6.QtPdf")

    def test_a_blank_image_claims_nothing(self):
        from makeyourtree_studio.guide.inspect import analyse

        white = np.ones((60, 60, 3), dtype=np.float32)
        reading = analyse(white)
        assert reading.observations == []
        assert reading.suggested == {}

    def test_a_ring_of_ink_reads_as_circular(self):
        from makeyourtree_studio.guide.inspect import analyse

        size = 200
        yy, xx = np.mgrid[0:size, 0:size]
        radius = np.hypot(yy - size / 2, xx - size / 2)
        ring = (radius > size * 0.30) & (radius < size * 0.45)
        image = np.ones((size, size, 3), dtype=np.float32)
        image[ring] = 0.0
        assert analyse(image).suggested.get("shape") == "circular"

    def test_a_wide_block_of_ink_reads_as_rectangular(self):
        from makeyourtree_studio.guide.inspect import analyse

        image = np.ones((80, 300, 3), dtype=np.float32)
        image[20:60, 20:280] = 0.0
        assert analyse(image).suggested.get("shape") == "rectangular"

    def test_grey_ink_alone_means_no_annotation(self):
        from makeyourtree_studio.guide.inspect import analyse

        image = np.ones((80, 300, 3), dtype=np.float32)
        image[20:60, 20:280] = 0.2
        assert analyse(image).suggested.get("extra_data") == ["none"]


def test_progress_starts_at_zero():
    """A fresh interview must not claim credit for questions never shown.

    Two questions only become relevant once earlier answers make them so, and
    counting those as answered made the first page read '2 of 8'.
    """
    assert GuideSession().progress()[0] == 0


def test_progress_counts_skips_as_dealt_with():
    session = GuideSession()
    session.skip("goal")
    assert session.progress()[0] == 1


def test_the_total_grows_as_the_interview_branches():
    session = GuideSession()
    before = session.progress()[1]
    session.answer("tip_count", "thousands")   # unlocks the label question
    session.answer("extra_data", ["category"])  # unlocks the colour question
    assert session.progress()[1] > before


# ------------------------------------------------------------ extra features


def test_everything_expands_to_the_full_set():
    """"As many as sensibly fit" must not quietly mean "all but the newest"."""
    from makeyourtree.guide.questions import question, wanted_extras

    expanded = wanted_extras({"extras": ["everything"]})
    offered = {c.value for c in question("extras").choices
               if c.value not in ("everything", "none")}
    # `dark` is deliberately excluded: it is a background choice, not an
    # addition, and most journals want white.
    assert set(expanded) <= offered
    assert len(expanded) >= 5


def test_none_beats_the_other_choices():
    from makeyourtree.guide.questions import wanted_extras

    assert wanted_extras({"extras": ["none"]}) == []


def test_each_extra_becomes_its_own_step():
    plan = build_plan({"extras": ["support", "scale_bar"]})
    plan.step("extra-support")
    plan.step("extra-scale_bar")


def test_asking_for_everything_earns_a_word_of_restraint():
    """A figure carrying every feature at once is a demo, not an argument."""
    plan = build_plan({"extras": ["everything"]})
    step = plan.step("extra-restraint")
    assert step.optional
    assert "not carrying an argument" in step.detail


def test_a_few_extras_do_not_trigger_the_warning():
    plan = build_plan({"extras": ["support"]})
    with pytest.raises(KeyError):
        plan.step("extra-restraint")


def test_extras_combine_with_data_tracks():
    plan = build_plan({"extra_data": ["category", "matrix"],
                       "extras": ["support", "scale_bar"]})
    for key in ("data-category", "data-matrix", "extra-support",
                "extra-scale_bar", "align"):
        plan.step(key)

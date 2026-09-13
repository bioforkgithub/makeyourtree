# SPDX-License-Identifier: MIT
"""Guided help: work out what figure to make, and keep your place while you do.

Two ways in, one destination. The interview in :mod:`.questions` asks about the
data and where the figure is going; :mod:`.figure` measures a published figure
and pre-fills what it can prove. Either way :mod:`.recipe` turns the answers
into an ordered :class:`~makeyourtree.guide.plan.Plan` that saves to disk, so
work interrupted on Monday resumes on Thursday.
"""
from .figure import (FigureError, FigureReading, InspectorUnavailable,
                     Observation, inspect_figure, inspector_available)
from .plan import (PLAN_EXTENSION, Plan, PlanError, Step, load_plan, save_plan)
from .questions import QUESTIONS, Choice, Question, next_question, remaining
from .recipe import build_plan, recommend_layout

__all__ = [
    "Plan", "Step", "PlanError", "PLAN_EXTENSION", "save_plan", "load_plan",
    "Question", "Choice", "QUESTIONS", "next_question", "remaining",
    "build_plan", "recommend_layout",
    "Observation", "FigureReading", "FigureError", "InspectorUnavailable",
    "inspect_figure", "inspector_available",
]

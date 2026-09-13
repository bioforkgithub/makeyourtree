# SPDX-License-Identifier: MIT
"""Shared test fixtures.

Adds ``src`` to the path so the suite runs from a clean checkout without an
install step, and forces Qt offscreen so studio tests never try to open a
window in CI.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture
def sink():
    from makeyourtree.core.diagnostics import DiagnosticSink
    return DiagnosticSink()


@pytest.fixture
def metrics():
    from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics
    return CachedMetrics(FallbackMetrics())

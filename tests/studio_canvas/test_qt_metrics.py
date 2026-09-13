# SPDX-License-Identifier: MIT
"""QtMetrics: linear in size, never zero, sane with no fonts installed."""

from __future__ import annotations

import pytest

from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics, TextMetrics

from makeyourtree_studio.canvas.qt_metrics import (REFERENCE_PIXEL_SIZE, QtMetrics,
                                               font_families, qt_font)


def test_satisfies_the_core_protocol(qapp):
    assert isinstance(QtMetrics(), TextMetrics)


def test_no_fonts_falls_back_instead_of_measuring_zero(qapp):
    """The offscreen platform reports no families at all.

    A zero advance would collapse ``tip_offset`` and drop every track on top of
    the tree, so the class must notice and delegate.
    """
    m = QtMetrics()
    width = m.advance("Homo sapiens", 11.0)
    assert width > 0.0
    if not m.usable:
        assert width == pytest.approx(
            FallbackMetrics().advance("Homo sapiens", 11.0))


def test_measurements_are_positive_and_ordered(qapp):
    m = QtMetrics()
    assert m.advance("", 11.0) == 0.0
    assert m.advance("i", 11.0) < m.advance("iiii", 11.0)
    assert m.line_height(11.0) > 0.0
    assert m.ascent(11.0) > 0.0
    assert m.descent(11.0) > 0.0
    assert m.ascent(11.0) + m.descent(11.0) <= m.line_height(11.0) * 1.5


def test_advance_is_linear_in_size(qapp):
    """Layout must not jump as a font-size slider moves through 10.5."""
    m = QtMetrics()
    base = m.advance("Escherichia coli", 10.0)
    assert m.advance("Escherichia coli", 20.0) == pytest.approx(2.0 * base, rel=1e-6)
    assert m.advance("Escherichia coli", 10.5) == pytest.approx(1.05 * base, rel=1e-6)


def test_ellipsize_fits_the_budget(qapp):
    m = QtMetrics()
    text = "Mycobacterium tuberculosis H37Rv"
    full = m.advance(text, 11.0)
    out = m.ellipsize(text, 11.0, full / 3.0)
    assert out != text
    assert m.advance(out, 11.0) <= full / 3.0 + 1e-6
    assert m.ellipsize(text, 11.0, full * 2.0) == text
    assert m.ellipsize(text, 11.0, 0.0) == ""
    assert m.ellipsize("", 11.0, 100.0) == ""


def test_fonts_are_cached_by_style(qapp):
    """One QFont per (family, size, bold, italic); a 100k-label tree must not
    rebuild the same face per label."""
    a = qt_font("Inter, sans-serif", bold=True)
    b = qt_font("Inter, sans-serif", bold=True)
    assert a is b
    assert qt_font("Inter, sans-serif", bold=False) is not a
    assert a.pixelSize() == REFERENCE_PIXEL_SIZE
    assert a.bold() is True


def test_css_family_stack_is_split_into_names_and_a_hint(qapp):
    names, hint = font_families("Inter, 'Segoe UI', monospace")
    assert names == ["Inter", "Segoe UI"]
    assert hint is not None
    assert font_families(None)[0] == []


def test_wraps_cleanly_in_cached_metrics(qapp):
    """The studio always wraps at the call site; the cache must be transparent."""
    inner = QtMetrics()
    cached = CachedMetrics(inner)
    for _ in range(3):
        assert cached.advance("Danio rerio", 11.0) == pytest.approx(
            inner.advance("Danio rerio", 11.0))
    assert cached.line_height(11.0) == pytest.approx(inner.line_height(11.0))
    assert cached.max_advance(["a", "abcdef", "abc"], 11.0) == pytest.approx(
        inner.advance("abcdef", 11.0))

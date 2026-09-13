# SPDX-License-Identifier: MIT
"""Font measurement backed by Qt, with a working fallback when Qt has no fonts.

The layout engine reserves label space before anything is drawn, so its idea of
how wide a string is has to match what the canvas will actually paint.  The core
cannot import Qt, so it measures through the
:class:`~makeyourtree.text.metrics.TextMetrics` protocol; this module is the
implementation the studio injects.

Two decisions matter here.

**Reference-size measurement.**  ``QFont`` takes an integer pixel size, but scene
units are continuous and a label may be 10.5 units tall.  Rounding the font size
would make layout jump as a slider moves and, worse, would disagree with the
painter.  So every face is built once at :data:`REFERENCE_PIXEL_SIZE` and every
measurement is scaled linearly from it.  :mod:`makeyourtree_studio.canvas.qt_backend`
draws through the same reference font under a painter scale, so the width the
layout reserved is exactly the width that gets painted.

**The zero-font case.**  The offscreen platform, which is what CI runs, reports
no font families at all, and a ``QFontMetricsF`` built there returns zero
advances.  A zero-width label does not merely look wrong: ``tip_offset``
collapses, tracks land on top of the tree and the whole layout is garbage.  So
the class probes at construction and delegates to
:class:`~makeyourtree.text.metrics.FallbackMetrics` when Qt cannot measure, which
keeps geometry sane in CI and on a misconfigured machine alike.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF, QGuiApplication

from makeyourtree.text.metrics import FallbackMetrics

__all__ = ["QtMetrics", "REFERENCE_PIXEL_SIZE", "qt_font", "font_families",
           "qt_fonts_available"]

REFERENCE_PIXEL_SIZE = 64
"""Pixel size every face is instantiated at.  Large enough that hinting noise is
below a tenth of a percent when scaled down to a typical 11-unit label, small
enough that the Qt glyph cache is not stressed."""

_GENERIC = {"sans-serif": QFont.StyleHint.SansSerif,
            "serif": QFont.StyleHint.Serif,
            "monospace": QFont.StyleHint.Monospace,
            "cursive": QFont.StyleHint.Cursive,
            "fantasy": QFont.StyleHint.Fantasy,
            "system-ui": QFont.StyleHint.System}

_FONT_CACHE: dict[tuple[str | None, int, bool, bool], QFont] = {}


def font_families(family: str | None) -> tuple[list[str], QFont.StyleHint]:
    """Split a CSS-style family list into concrete names plus a generic hint.

    Themes carry web-style stacks (``Inter, Segoe UI, sans-serif``) because the
    same string has to work in the SVG export, where it is a CSS value.  Qt wants
    a list of real family names and a separate style hint for the generic tail.
    """
    hint = QFont.StyleHint.SansSerif
    names: list[str] = []
    if not family:
        return names, hint
    for part in family.split(","):
        name = part.strip().strip("'").strip('"')
        if not name:
            continue
        generic = _GENERIC.get(name.lower())
        if generic is not None:
            hint = generic
        else:
            names.append(name)
    return names, hint


def qt_font(family: str | None, pixel_size: int = REFERENCE_PIXEL_SIZE, *,
            bold: bool = False, italic: bool = False) -> QFont:
    """A cached ``QFont``.

    Cached because building one is a font-database lookup, and a 100 000-label
    tree would otherwise repeat it 100 000 times for the same handful of styles.
    """
    key = (family, int(pixel_size), bool(bold), bool(italic))
    hit = _FONT_CACHE.get(key)
    if hit is not None:
        return hit
    names, hint = font_families(family)
    font = QFont()
    if names:
        font.setFamilies(names)
    font.setStyleHint(hint)
    font.setPixelSize(max(1, int(pixel_size)))
    font.setBold(bool(bold))
    font.setItalic(bool(italic))
    # Hinting would make advances non-linear in size and break the reference
    # scaling above, so ask Qt for unhinted outline metrics instead.
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    _FONT_CACHE[key] = font
    return font


def qt_fonts_available() -> bool:
    """Whether Qt can measure text at all in this process."""
    if QGuiApplication.instance() is None:
        return False
    try:
        return bool(QFontDatabase.families())
    except RuntimeError:  # pragma: no cover - defensive; no QPA plugin
        return False


class QtMetrics:
    """:class:`~makeyourtree.text.metrics.TextMetrics` over ``QFontMetricsF``.

    Wrap an instance in :class:`~makeyourtree.text.metrics.CachedMetrics` at the call
    site: measuring the same label twice is pure waste, and the cache belongs to
    the caller so it can be dropped when the theme font changes.
    """

    __slots__ = ("family", "_fm", "_fallback", "_usable")

    def __init__(self, family: str | None = None) -> None:
        self.family = family
        self._fm: dict[tuple[str | None, bool, bool], QFontMetricsF] = {}
        self._fallback = FallbackMetrics()
        self._usable = self._probe()

    # ------------------------------------------------------------ internals

    @property
    def usable(self) -> bool:
        """False when Qt reported no fonts, so every call is delegated."""
        return self._usable

    def _probe(self) -> bool:
        if not qt_fonts_available():
            return False
        try:
            fm = self._metrics(self.family, False, False)
            return fm.horizontalAdvance("Mg") > 0.0 and fm.height() > 0.0
        except (RuntimeError, TypeError):  # pragma: no cover - defensive
            return False

    def _metrics(self, family: str | None, bold: bool,
                 italic: bool) -> QFontMetricsF:
        key = (family, bold, italic)
        hit = self._fm.get(key)
        if hit is None:
            hit = QFontMetricsF(qt_font(family, bold=bold, italic=italic))
            self._fm[key] = hit
        return hit

    def _for(self, family: str | None, bold: bool = False,
             italic: bool = False) -> QFontMetricsF:
        return self._metrics(family or self.family, bold, italic)

    # ------------------------------------------------------------ measuring

    def advance(self, text: str, size: float, *, bold: bool = False,
                italic: bool = False, family: str | None = None) -> float:
        if not text:
            return 0.0
        if not self._usable:
            return self._fallback.advance(text, size, bold=bold, italic=italic,
                                          family=family)
        w = self._for(family, bold, italic).horizontalAdvance(text)
        if w <= 0.0:
            # A face that measures to nothing would collapse the layout.  The
            # estimate is wrong by a few percent, which is survivable; zero is not.
            return self._fallback.advance(text, size, bold=bold, italic=italic,
                                          family=family)
        return w * size / REFERENCE_PIXEL_SIZE

    def line_height(self, size: float, family: str | None = None) -> float:
        if not self._usable:
            return self._fallback.line_height(size, family)
        h = self._for(family).height()
        if h <= 0.0:
            return self._fallback.line_height(size, family)
        return h * size / REFERENCE_PIXEL_SIZE

    def ascent(self, size: float, family: str | None = None) -> float:
        if not self._usable:
            return self._fallback.ascent(size, family)
        a = self._for(family).ascent()
        if a <= 0.0:
            return self._fallback.ascent(size, family)
        return a * size / REFERENCE_PIXEL_SIZE

    def descent(self, size: float, family: str | None = None) -> float:
        if not self._usable:
            return self._fallback.descent(size, family)
        d = self._for(family).descent()
        if d <= 0.0:
            return self._fallback.descent(size, family)
        return d * size / REFERENCE_PIXEL_SIZE

    def ellipsize(self, text: str, size: float, max_width: float, **kw) -> str:
        if not text or max_width <= 0:
            return ""
        if not self._usable or size <= 0:
            return self._fallback.ellipsize(text, size, max_width, **kw)
        fm = self._for(kw.get("family"), bool(kw.get("bold", False)),
                       bool(kw.get("italic", False)))
        # elidedText works in font units, so the budget scales up by exactly the
        # factor advances scale down by.
        budget = max_width * REFERENCE_PIXEL_SIZE / size
        out = fm.elidedText(text, Qt.TextElideMode.ElideRight, budget)
        return out if out else self._fallback.ellipsize(text, size, max_width, **kw)

    def max_advance(self, texts: Iterable[str], size: float, **kw) -> float:
        """Widest advance over *texts*.  Mirrors ``CachedMetrics.max_advance``."""
        best = 0.0
        for t in texts:
            if not t:
                continue
            w = self.advance(t, size, **kw)
            if w > best:
                best = w
        return best

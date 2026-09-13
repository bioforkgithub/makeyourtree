# SPDX-License-Identifier: MIT
"""Font measurement.

Layout has to know how wide a label is before it can decide where tracks
start, but the core must not import Qt.  So measurement is an interface: the
studio injects a ``QFontMetricsF``-backed implementation, while the headless
core, the CLI and the test suite use :class:`FallbackMetrics`.

:class:`FallbackMetrics` estimates advance widths from a per-character width
table for a typical humanist sans at 1 em.  It is not exact -- nothing short of
a real shaping engine is -- but it is within a few percent for Latin text,
which is enough to reserve label space.  Anything that must be pixel-exact
(the interactive canvas) uses the Qt implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["TextMetrics", "FallbackMetrics", "CachedMetrics", "default_metrics"]


@runtime_checkable
class TextMetrics(Protocol):
    """Measures strings for the layout engine."""

    def advance(self, text: str, size: float, *, bold: bool = False,
                italic: bool = False, family: str | None = None) -> float:
        """Horizontal advance width of *text* at *size* points."""
        ...

    def line_height(self, size: float, family: str | None = None) -> float:
        """Distance between successive baselines."""
        ...

    def ascent(self, size: float, family: str | None = None) -> float: ...

    def descent(self, size: float, family: str | None = None) -> float: ...

    def ellipsize(self, text: str, size: float, max_width: float, **kw) -> str:
        """Shorten *text* with a trailing ellipsis so it fits *max_width*."""
        ...


# Advance widths at 1 em, keyed by character class.  Derived by averaging the
# metrics of several open-licence humanist sans faces (DejaVu Sans, Open Sans,
# Source Sans) -- not copied from any single font's tables.
_NARROW = set("iljItf.,;:!|'`()[]{}/\\ ")
_WIDE = set("mwMW@%")
_DIGIT = set("0123456789")


class FallbackMetrics:
    """Qt-free approximation.  Deterministic, so golden tests stay stable."""

    __slots__ = ("_em", "_cache")

    def __init__(self, em_factor: float = 1.0) -> None:
        self._em = em_factor
        self._cache: dict[tuple[str, bool], float] = {}

    def _em_width(self, text: str, bold: bool) -> float:
        key = (text, bold)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        total = 0.0
        for ch in text:
            if ch in _NARROW:
                w = 0.30
            elif ch in _WIDE:
                w = 0.86
            elif ch in _DIGIT:
                w = 0.55
            elif ch.isupper():
                w = 0.66
            elif ch.isspace():
                w = 0.28
            elif ord(ch) > 0x2E80:
                w = 1.0          # CJK and friends are full-width
            else:
                w = 0.52
            total += w
        if bold:
            total *= 1.05
        if len(self._cache) < 20000:
            self._cache[key] = total
        return total

    def advance(self, text: str, size: float, *, bold: bool = False,
                italic: bool = False, family: str | None = None) -> float:
        if not text:
            return 0.0
        return self._em_width(text, bold) * size * self._em

    def line_height(self, size: float, family: str | None = None) -> float:
        return size * 1.32

    def ascent(self, size: float, family: str | None = None) -> float:
        return size * 0.80

    def descent(self, size: float, family: str | None = None) -> float:
        return size * 0.22

    def ellipsize(self, text: str, size: float, max_width: float, **kw) -> str:
        if max_width <= 0 or not text:
            return ""
        if self.advance(text, size, **kw) <= max_width:
            return text
        ell = "…"
        ell_w = self.advance(ell, size, **kw)
        budget = max_width - ell_w
        if budget <= 0:
            return ell
        # Binary search the cut point; advance() is monotonic in prefix length.
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.advance(text[:mid], size, **kw) <= budget:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + ell


class CachedMetrics:
    """Memoising wrapper around any :class:`TextMetrics`.

    Measuring 100 000 labels through a Qt call is measurable; measuring them
    twice is not acceptable.  Keyed on the full style tuple so bold and italic
    variants do not collide.
    """

    __slots__ = ("_inner", "_cache", "_limit")

    def __init__(self, inner: TextMetrics, limit: int = 200_000) -> None:
        self._inner = inner
        self._cache: dict[tuple, float] = {}
        self._limit = limit

    def advance(self, text: str, size: float, *, bold: bool = False,
                italic: bool = False, family: str | None = None) -> float:
        key = (text, size, bold, italic, family)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._inner.advance(text, size, bold=bold, italic=italic, family=family)
            if len(self._cache) < self._limit:
                self._cache[key] = hit
        return hit

    def line_height(self, size: float, family: str | None = None) -> float:
        return self._inner.line_height(size, family)

    def ascent(self, size: float, family: str | None = None) -> float:
        return self._inner.ascent(size, family)

    def descent(self, size: float, family: str | None = None) -> float:
        return self._inner.descent(size, family)

    def ellipsize(self, text: str, size: float, max_width: float, **kw) -> str:
        return self._inner.ellipsize(text, size, max_width, **kw)

    def clear(self) -> None:
        self._cache.clear()

    def max_advance(self, texts, size: float, **kw) -> float:
        """Widest advance over *texts*.  Convenience for label-space solving."""
        best = 0.0
        for t in texts:
            if not t:
                continue
            w = self.advance(t, size, **kw)
            if w > best:
                best = w
        return best


_DEFAULT: CachedMetrics | None = None


def default_metrics() -> CachedMetrics:
    """Process-wide fallback metrics.  The studio replaces this at startup."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = CachedMetrics(FallbackMetrics())
    return _DEFAULT

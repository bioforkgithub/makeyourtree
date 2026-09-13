# SPDX-License-Identifier: MIT
"""Colour value type.

Deliberately dependency-free: the core must render SVG without Qt, so colours
are plain immutable RGBA tuples with parsing and blending helpers rather than
``QColor``.  The Qt backend converts at the boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["Color", "parse_color", "TRANSPARENT"]

_HEX3 = re.compile(r"^#?([0-9a-fA-F]{3})$")
_HEX4 = re.compile(r"^#?([0-9a-fA-F]{4})$")
_HEX6 = re.compile(r"^#?([0-9a-fA-F]{6})$")
_HEX8 = re.compile(r"^#?([0-9a-fA-F]{8})$")
_FUNC = re.compile(r"^(rgba?|hsla?)\(([^)]*)\)$", re.I)

# A small set of names actually used by tree files and by our own defaults.
# Not the full CSS list -- files that need exotic names use hex.
_NAMED: dict[str, str] = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "cyan": "#00ffff", "magenta": "#ff00ff",
    "grey": "#808080", "gray": "#808080", "lightgrey": "#d3d3d3", "lightgray": "#d3d3d3",
    "darkgrey": "#a9a9a9", "darkgray": "#a9a9a9", "orange": "#ffa500",
    "purple": "#800080", "brown": "#a52a2a", "pink": "#ffc0cb", "navy": "#000080",
    "teal": "#008080", "olive": "#808000", "maroon": "#800000", "lime": "#00ff00",
    "silver": "#c0c0c0", "gold": "#ffd700", "indigo": "#4b0082", "violet": "#ee82ee",
    "salmon": "#fa8072", "khaki": "#f0e68c", "turquoise": "#40e0d0",
    "none": "#00000000", "transparent": "#00000000",
}


@dataclass(frozen=True, slots=True)
class Color:
    """An 8-bit-per-channel RGBA colour.  Channels are 0-255, alpha 0-255."""

    r: int
    g: int
    b: int
    a: int = 255

    # ------------------------------------------------------------ construct

    @staticmethod
    def from_hex(s: str) -> "Color":
        return parse_color(s)

    @staticmethod
    def from_float(r: float, g: float, b: float, a: float = 1.0) -> "Color":
        cl = lambda v: max(0, min(255, int(round(v * 255))))  # noqa: E731
        return Color(cl(r), cl(g), cl(b), cl(a))

    @staticmethod
    def from_hsl(h: float, s: float, ll: float, a: float = 1.0) -> "Color":
        """*h* in degrees, *s* and *ll* in 0..1."""
        h = (h % 360.0) / 360.0
        if s <= 0:
            return Color.from_float(ll, ll, ll, a)
        q = ll * (1 + s) if ll < 0.5 else ll + s - ll * s
        p = 2 * ll - q

        def hue(t: float) -> float:
            t = t % 1.0
            if t < 1 / 6:
                return p + (q - p) * 6 * t
            if t < 1 / 2:
                return q
            if t < 2 / 3:
                return p + (q - p) * (2 / 3 - t) * 6
            return p

        return Color.from_float(hue(h + 1 / 3), hue(h), hue(h - 1 / 3), a)

    # --------------------------------------------------------------- render

    @property
    def hex(self) -> str:
        """``#rrggbb``, or ``#rrggbbaa`` when not fully opaque."""
        base = f"#{self.r:02x}{self.g:02x}{self.b:02x}"
        return base if self.a == 255 else base + f"{self.a:02x}"

    @property
    def rgb_hex(self) -> str:
        """Always ``#rrggbb``; alpha is dropped.  SVG wants this plus fill-opacity."""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    @property
    def opacity(self) -> float:
        return self.a / 255.0

    @property
    def rgba_tuple(self) -> tuple[int, int, int, int]:
        return (self.r, self.g, self.b, self.a)

    def css(self) -> str:
        if self.a == 255:
            return self.rgb_hex
        return f"rgba({self.r},{self.g},{self.b},{self.opacity:.3g})"

    # ------------------------------------------------------------ transform

    def with_alpha(self, a: float | int) -> "Color":
        """*a* as a float 0..1 or an int 0..255."""
        av = int(round(a * 255)) if isinstance(a, float) and a <= 1.0 else int(a)
        return Color(self.r, self.g, self.b, max(0, min(255, av)))

    def lerp(self, other: "Color", t: float) -> "Color":
        """Linear blend in sRGB space.  ``t=0`` is self, ``t=1`` is *other*."""
        t = max(0.0, min(1.0, t))
        m = lambda x, y: int(round(x + (y - x) * t))  # noqa: E731
        return Color(m(self.r, other.r), m(self.g, other.g),
                     m(self.b, other.b), m(self.a, other.a))

    def lighten(self, amount: float) -> "Color":
        return self.lerp(Color(255, 255, 255, self.a), amount)

    def darken(self, amount: float) -> "Color":
        return self.lerp(Color(0, 0, 0, self.a), amount)

    @property
    def luminance(self) -> float:
        """Relative luminance per WCAG 2.x, used to pick readable text over a fill."""
        def ch(v: int) -> float:
            c = v / 255.0
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(self.r) + 0.7152 * ch(self.g) + 0.0722 * ch(self.b)

    def contrast_ratio(self, other: "Color") -> float:
        a, b = self.luminance, other.luminance
        hi, lo = max(a, b), min(a, b)
        return (hi + 0.05) / (lo + 0.05)

    def readable_text(self, light: "Color | None" = None,
                      dark: "Color | None" = None) -> "Color":
        """Pick whichever of *light* / *dark* contrasts better against this fill."""
        light = light or Color(255, 255, 255)
        dark = dark or Color(17, 17, 17)
        return dark if self.contrast_ratio(dark) >= self.contrast_ratio(light) else light

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.hex


TRANSPARENT = Color(0, 0, 0, 0)


def parse_color(value: "str | Color | tuple | None") -> Color:
    """Parse a colour from hex, ``rgb()``/``rgba()``/``hsl()``, a name or a tuple.

    Raises :class:`ValueError` on anything unrecognised so that annotation
    loaders can report the offending cell rather than silently drawing black.
    """
    if value is None:
        return TRANSPARENT
    if isinstance(value, Color):
        return value
    if isinstance(value, (tuple, list)):
        vals = list(value)
        if len(vals) == 3:
            vals.append(255)
        if len(vals) != 4:
            raise ValueError(f"colour tuple needs 3 or 4 components, got {len(vals)}")
        if all(isinstance(v, float) and v <= 1.0 for v in vals):
            return Color.from_float(*vals)
        return Color(*(int(v) for v in vals))

    s = str(value).strip()
    if not s:
        return TRANSPARENT
    low = s.lower()
    if low in _NAMED:
        s = _NAMED[low]

    m = _HEX6.match(s)
    if m:
        h = m.group(1)
        return Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = _HEX8.match(s)
    if m:
        h = m.group(1)
        return Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    m = _HEX3.match(s)
    if m:
        h = m.group(1)
        return Color(int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
    m = _HEX4.match(s)
    if m:
        h = m.group(1)
        return Color(int(h[0] * 2, 16), int(h[1] * 2, 16),
                     int(h[2] * 2, 16), int(h[3] * 2, 16))

    m = _FUNC.match(s)
    if m:
        fn = m.group(1).lower()
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(2)) if p.strip()]
        if len(parts) not in (3, 4):
            raise ValueError(f"cannot parse colour {value!r}")

        def num(p: str, scale: float = 1.0) -> float:
            if p.endswith("%"):
                return float(p[:-1]) / 100.0 * scale
            return float(p)

        alpha = num(parts[3], 1.0) if len(parts) == 4 else 1.0
        if alpha > 1.0:
            alpha /= 255.0
        if fn.startswith("rgb"):
            comps = [num(p, 255.0) for p in parts[:3]]
            return Color(*(max(0, min(255, int(round(c)))) for c in comps),
                         max(0, min(255, int(round(alpha * 255)))))
        return Color.from_hsl(num(parts[0]), num(parts[1], 1.0),
                              num(parts[2], 1.0), alpha)

    raise ValueError(f"cannot parse colour {value!r}")

# SPDX-License-Identifier: MIT
"""Named colour palettes and the OKLab interpolation used to sample them.

Three families, because they answer three different questions about the data:

``CATEGORICAL``
    Unordered labels.  Every colour must be tellable from every other, including
    by the ~8 % of men with a red-green deficiency, so the default is the
    Colour Universal Design set of Okabe & Ito (2008), *How to make figures and
    presentations that are friendly to colour blind people*, and the rest are
    Paul Tol's schemes (SRON technical note SRON/EPS/TN/09-002, published for
    free reuse), which were designed against the same constraint.
``SEQUENTIAL``
    One-directional magnitude.  The ramps here are monotone in relative
    luminance, which is what "perceptually uniform" buys: the ordering survives
    greyscale printing and survives every form of dichromacy, because lightness
    is the one channel no colour deficiency removes.  viridis / magma /
    plasma / inferno are from matplotlib and are released CC0 (public domain);
    cividis is from Nuñez, Anderton & Renslow (2018), *Optimizing colormaps
    with consideration for color vision deficiency*, PLOS ONE, also CC0.  The
    single-hue ramps are generated for MakeYourTree from constant-hue HSL sweeps.
``DIVERGING``
    Magnitude away from a meaningful centre.  Two monotone arms about a neutral
    midpoint; the domain must be symmetric about that midpoint or the colours
    lie about which side is larger.  Values from ColorBrewer (Brewer, Harrower
    & Pennsylvania State University; Apache-2.0) and from Tol's ``sunset``.

Interpolation is done in OKLab (Ottosson 2020, *A perceptual color space for
image processing*), not in sRGB: blending ``#0072B2`` and ``#F0E442`` in sRGB
passes through a muddy grey, whereas OKLab keeps the intermediate lightness
where the eye expects it.  Sampling exactly on a control point short-circuits
the round trip so that :meth:`Palette.sample` reproduces the published hex
values bit for bit.

Red-green ramps are deliberately absent: they are the single worst choice for
deuteranopia and there is always a better option here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping

from .color import Color, parse_color

__all__ = ["Palette", "CATEGORICAL", "SEQUENTIAL", "DIVERGING", "get_palette",
           "list_palettes", "assign_categories", "oklab_mix", "oklab_distance",
           "to_oklab", "from_oklab"]

KINDS: tuple[str, ...] = ("categorical", "sequential", "diverging")


# ------------------------------------------------------------------- OKLab


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (c ** (1 / 2.4)) - 0.055


def _cbrt(x: float) -> float:
    # Copysign so that out-of-gamut negatives round-trip instead of raising.
    return math.copysign(abs(x) ** (1 / 3), x)


def to_oklab(c: Color) -> tuple[float, float, float]:
    """Convert to OKLab ``(L, a, b)``.  Matrices from Ottosson (2020)."""
    r = _srgb_to_linear(c.r / 255.0)
    g = _srgb_to_linear(c.g / 255.0)
    b = _srgb_to_linear(c.b / 255.0)
    l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def from_oklab(lab: tuple[float, float, float], alpha: int = 255) -> Color:
    """Inverse of :func:`to_oklab`, clipped back into the sRGB cube."""
    L, a, b = lab
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rl = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    gl = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    ch = lambda v: max(0, min(255, int(round(_linear_to_srgb(v) * 255))))  # noqa: E731
    return Color(ch(rl), ch(gl), ch(bl), alpha)


def oklab_mix(a: Color, b: Color, t: float) -> Color:
    """Perceptual blend.  ``t=0`` is *a*, ``t=1`` is *b*; endpoints are exact."""
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    la, lb = to_oklab(a), to_oklab(b)
    mix = tuple(x + (y - x) * t for x, y in zip(la, lb))
    alpha = int(round(a.a + (b.a - a.a) * t))
    return from_oklab(mix, alpha)  # type: ignore[arg-type]


def oklab_distance(a: Color, b: Color) -> float:
    """Euclidean OKLab distance -- a usable proxy for "can a reader tell these
    two swatches apart".  Roughly 0.02 is a just-noticeable difference for large
    patches; encoding palettes here stay above 0.08."""
    la, lb = to_oklab(a), to_oklab(b)
    return math.dist(la, lb)


# ------------------------------------------------------------------ palette


@dataclass(frozen=True, slots=True)
class Palette:
    """An ordered list of colours plus the metadata needed to use it correctly.

    The same container serves discrete and continuous use: ``cycle`` treats the
    colours as a repeating list of category swatches, ``sample`` treats them as
    control points of a piecewise-linear ramp.
    """

    name: str
    kind: str
    """One of :data:`KINDS`."""
    colors: tuple[Color, ...]
    origin: str = ""
    """Where the values came from, so the licence question stays answerable."""
    bad: Color | None = None
    """Swatch for missing data.  Chosen to sit outside the palette's own range
    so that "no value" never reads as a value."""
    encoding: bool = True
    """False for palettes meant as backgrounds or as text accents (their
    colours are deliberately close together and must not carry meaning)."""

    def __len__(self) -> int:
        return len(self.colors)

    def __iter__(self) -> Iterator[Color]:
        return iter(self.colors)

    def __getitem__(self, i: int) -> Color:
        return self.colors[i]

    @property
    def hex_colors(self) -> tuple[str, ...]:
        return tuple(c.hex for c in self.colors)

    def cycle(self, i: int) -> Color:
        """Category *i*, wrapping.  Negative indices wrap the same way."""
        return self.colors[i % len(self.colors)]

    def sample(self, t: float) -> Color:
        """Interpolate the ramp at *t* in 0..1.

        ``sample(0)`` and ``sample(1)`` return the first and last control point
        unchanged -- legends draw the ramp and cells draw single samples, and
        the two must agree exactly at the ends.
        """
        n = len(self.colors)
        if n == 1:
            return self.colors[0]
        t = 0.0 if t != t else max(0.0, min(1.0, t))  # NaN -> 0
        pos = t * (n - 1)
        i = min(int(math.floor(pos)), n - 2)
        f = pos - i
        if f <= 0.0:
            return self.colors[i]
        if f >= 1.0:
            return self.colors[i + 1]
        return oklab_mix(self.colors[i], self.colors[i + 1], f)

    def resample(self, n: int) -> tuple[Color, ...]:
        """*n* colours evenly spaced along the ramp, endpoints included.

        Used for legend gradient bars and for binned scales, which need a fixed
        number of swatches regardless of how many control points exist.
        """
        if n <= 0:
            return ()
        if n == 1:
            return (self.sample(0.5),)
        return tuple(self.sample(i / (n - 1)) for i in range(n))

    def reversed(self) -> "Palette":
        """The same ramp read the other way; ``blues`` light-to-dark becomes
        dark-to-light without inventing a second named palette."""
        return Palette(f"{self.name}-r", self.kind, tuple(reversed(self.colors)),
                       self.origin, self.bad, self.encoding)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Palette {self.name!r} {self.kind} n={len(self.colors)}>"


def _pal(name: str, kind: str, hexes: str, origin: str, *,
         bad: str | None = None, encoding: bool = True) -> Palette:
    return Palette(name, kind, tuple(parse_color(h) for h in hexes.split()),
                   origin, parse_color(bad) if bad else None, encoding)


# -------------------------------------------------------------- categorical

_CUD = "Okabe & Ito (2008), Colour Universal Design; published as research"
_TOL = "Paul Tol, SRON/EPS/TN/09-002; published for free reuse"

CATEGORICAL: dict[str, Palette] = {p.name: p for p in (
    # The CUD eight.  Black last so that a two-category plot is orange/blue,
    # the pair with the largest separation under every form of dichromacy.
    _pal("okabe-ito", "categorical",
         "#E69F00 #56B4E9 #009E73 #F0E442 #0072B2 #D55E00 #CC79A7 #000000",
         _CUD, bad="#BBBBBB"),
    _pal("tol-bright", "categorical",
         "#4477AA #EE6677 #228833 #CCBB44 #66CCEE #AA3377", _TOL, bad="#BBBBBB"),
    _pal("tol-vibrant", "categorical",
         "#EE7733 #0077BB #33BBEE #EE3377 #CC3311 #009988", _TOL, bad="#BBBBBB"),
    _pal("tol-muted", "categorical",
         "#CC6677 #332288 #DDCC77 #117733 #88CCEE #882255 #44AA99 #999933 #AA4499",
         _TOL, bad="#DDDDDD"),
    _pal("tol-light", "categorical",
         "#77AADD #EE8866 #EEDD88 #FFAABB #99DDFF #44BB99 #BBCC33 #AAAA00",
         _TOL, bad="#DDDDDD"),
    # Three colours that stay distinct in greyscale as well as in colour, for
    # print figures and for line marks where hue alone is too thin to read.
    _pal("tol-high-contrast", "categorical",
         "#004488 #BB5566 #DDAA33", _TOL, bad="#BBBBBB"),
    # Washes behind text and text over those washes.  Not for encoding: the
    # members are intentionally close together.
    _pal("tol-pale", "categorical",
         "#BBCCEE #FFCCCC #CCDDAA #EEEEBB #CCEEFF", _TOL, bad="#DDDDDD",
         encoding=False),
    _pal("tol-dark", "categorical",
         "#222255 #663333 #225522 #666633 #225555", _TOL, bad="#555555",
         encoding=False),
)}


# --------------------------------------------------------------- sequential

_MPL = "matplotlib colormaps, released CC0 (public domain)"
_CIV = "Nuñez, Anderton & Renslow (2018) PLOS ONE, released CC0"
_OWN = "generated for MakeYourTree from a constant-hue HSL sweep"

SEQUENTIAL: dict[str, Palette] = {p.name: p for p in (
    _pal("viridis", "sequential",
         "#440154 #472D7B #3B528B #2C728E #21918C #27AD81 #5CC863 #AADC32 #FDE725",
         _MPL, bad="#DDDDDD"),
    _pal("magma", "sequential",
         "#000004 #1D1147 #51127C #832681 #B73779 #E55064 #FB8761 #FEC287 #FCFDBF",
         _MPL, bad="#DDDDDD"),
    _pal("inferno", "sequential",
         "#000004 #210C4A #57106E #8A226A #BC3754 #E35933 #F98C0A #F9C932 #FCFFA4",
         _MPL, bad="#DDDDDD"),
    _pal("plasma", "sequential",
         "#0D0887 #4C02A1 #7E03A8 #AA2395 #CC4778 #E56B5D #F89441 #FDC328 #F0F921",
         _MPL, bad="#DDDDDD"),
    _pal("cividis", "sequential",
         "#00224E #123570 #3B496C #575D6D #707173 #8A8678 #A59C74 #C3B369 #E1CC55 #FEE838",
         _CIV, bad="#DDDDDD"),
    # Single-hue ramps run light-to-dark so that an unfilled cell and a
    # zero-valued cell look alike, which is what a reader expects of a
    # "how much" strip anchored at zero.
    _pal("blues", "sequential",
         "#EDF3FA #B8CFED #7FAAE2 #4485DB #1F64BD #134587 #09274E", _OWN,
         bad="#DDDDDD"),
    _pal("greens", "sequential",
         "#EFF8F4 #BDE7D2 #88DAB1 #4ED18F #26B66E #16844D #0A4D2B", _OWN,
         bad="#DDDDDD"),
    _pal("oranges", "sequential",
         "#FDF3EA #F9D0AC #F5AC6D #F1892E #CF680D #914808 #522904", _OWN,
         bad="#DDDDDD"),
    _pal("greys", "sequential",
         "#F4F4F4 #D2D2D2 #B1B1B1 #8F8F8F #6E6E6E #4D4D4D #2B2B2B", _OWN,
         bad="#F0C4C4"),
)}


# ---------------------------------------------------------------- diverging

_CB = "ColorBrewer (Brewer & Harrower, Penn State), Apache-2.0"

DIVERGING: dict[str, Palette] = {p.name: p for p in (
    # Odd stop counts, midpoint at the centre index, so sample(0.5) lands on
    # the neutral colour exactly rather than one blend away from it.
    _pal("blue-red", "diverging",
         "#2166AC #4393C3 #92C5DE #D1E5F0 #F7F7F7 #FDDBC7 #F4A582 #D6604D #B2182B",
         _CB, bad="#FFEE99"),
    _pal("brown-teal", "diverging",
         "#8C510A #BF812D #DFC27D #F6E8C3 #F5F5F5 #C7EAE5 #80CDC1 #35978F #01665E",
         _CB, bad="#FFEE99"),
    _pal("purple-green", "diverging",
         "#762A83 #9970AB #C2A5CF #E7D4E8 #F7F7F7 #D9F0D3 #ACD39E #5AAE61 #1B7837",
         _CB, bad="#FFEE99"),
    # Cream rather than white in the middle: a near-white midpoint dissolves
    # into the page and mid-range values simply vanish.
    _pal("sunset", "diverging",
         "#364B9A #4A7BB7 #6EA6CD #98CAE1 #C2E4EF #EAECCC #FEDA8B #FDB366 #F67E4B "
         "#DD3D2D #A50026", _TOL, bad="#FFFFFF"),
)}


_BY_KIND: dict[str, dict[str, Palette]] = {
    "categorical": CATEGORICAL,
    "sequential": SEQUENTIAL,
    "diverging": DIVERGING,
}

# Names people reach for that are not the canonical ones.
_ALIASES: dict[str, str] = {
    "cud": "okabe-ito", "okabeito": "okabe-ito",
    "gray": "greys", "grays": "greys", "grey": "greys",
    "blue": "blues", "green": "greens", "orange": "oranges",
    "rdbu": "blue-red", "red-blue": "blue-red",
    "brbg": "brown-teal", "prgn": "purple-green",
}


def _norm(name: str) -> str:
    n = str(name).strip().lower().replace("_", "-").replace(" ", "-")
    return _ALIASES.get(n.replace("-", ""), _ALIASES.get(n, n))


def get_palette(name: str | Palette, kind: str | None = None) -> Palette:
    """Look up a palette by name, optionally restricted to one *kind*.

    Accepts a :class:`Palette` unchanged so that callers can take either a
    configured name or a caller-built palette without branching.  A trailing
    ``-r`` reverses the ramp, which is the common request that would otherwise
    double the size of the tables above.
    """
    if isinstance(name, Palette):
        return name
    key = _norm(name)
    reverse = False
    if key.endswith("-r") and key not in _ALL_NAMES:
        key, reverse = key[:-2], True
    if kind is not None and kind not in _BY_KIND:
        raise KeyError(f"unknown palette kind {kind!r}; known: {', '.join(KINDS)}")
    tables = [_BY_KIND[kind]] if kind else [CATEGORICAL, SEQUENTIAL, DIVERGING]
    for table in tables:
        p = table.get(key)
        if p is not None:
            return p.reversed() if reverse else p
    known = ", ".join(list_palettes(kind))
    raise KeyError(f"unknown palette {name!r}"
                   + (f" of kind {kind!r}" if kind else "") + f"; known: {known}")


def list_palettes(kind: str | None = None) -> list[str]:
    """Palette names, grouped by kind and alphabetical within a kind."""
    if kind is not None:
        if kind not in _BY_KIND:
            raise KeyError(f"unknown palette kind {kind!r}; known: {', '.join(KINDS)}")
        return sorted(_BY_KIND[kind])
    return [n for k in KINDS for n in sorted(_BY_KIND[k])]


_ALL_NAMES: frozenset[str] = frozenset(list_palettes())


# ------------------------------------------------------- category assignment


def assign_categories(values: Iterable[object], palette: str | Palette,
                      fixed: Mapping[str, object] | None = None,
                      ) -> dict[str, Color]:
    """Map category labels to colours in first-seen order.

    First-seen order is what makes the result stable: the same table always
    yields the same mapping, and appending rows never recolours the categories
    already present.  It does mean that re-ordering the *source* re-orders the
    colours, so callers that need colours pinned across a re-root or a filter
    should store the returned mapping and pass it back as *fixed*.

    User-fixed colours win, and the automatic assignment then avoids reusing
    them, so a pinned red does not collide with the palette's own red.
    """
    pal = get_palette(palette)
    pinned: dict[str, Color] = {}
    for k, v in (fixed or {}).items():
        pinned[str(k)] = v if isinstance(v, Color) else parse_color(v)  # type: ignore[arg-type]

    order: list[str] = []
    seen: set[str] = set()
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if not s or s == "-":
            continue
        if s not in seen:
            seen.add(s)
            order.append(s)
    for k in pinned:
        if k not in seen:
            seen.add(k)
            order.append(k)

    # One pass in first-seen order, so the mapping's own order is the order a
    # legend should list the categories in.
    used = {c.rgba_tuple for k, c in pinned.items() if k in seen}
    out: dict[str, Color] = {}
    i = 0
    for cat in order:
        c = pinned.get(cat)
        if c is None:
            c = pal.cycle(i)
            # Step over colours a pinned category already claimed, but give up
            # after one full lap so a fully pinned palette still terminates.
            for _ in range(len(pal)):
                if c.rgba_tuple not in used:
                    break
                i += 1
                c = pal.cycle(i)
            used.add(c.rgba_tuple)
            i += 1
        out[cat] = c
    return out


def distinct_colors(n: int, palette: str | Palette = "okabe-ito") -> tuple[Color, ...]:
    """*n* category colours.  Beyond the palette length the colours repeat --
    hue alone cannot separate more than about a dozen classes, so a caller
    asking for more should be grouping into "other" instead."""
    pal = get_palette(palette)
    return tuple(pal.cycle(i) for i in range(max(0, n)))


def _check_tables() -> None:
    """Guard the invariant the tables above are built to satisfy: every palette
    is registered under the kind it declares."""
    for kind, table in _BY_KIND.items():
        for name, p in table.items():
            if p.kind != kind or p.name != name:
                raise ValueError(f"palette table mismatch for {name!r}")


_check_tables()

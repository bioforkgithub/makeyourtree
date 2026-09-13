# SPDX-License-Identifier: MIT
"""Global visual defaults and per-node overrides.

Two levels, deliberately:

:class:`Theme`
    Document-wide defaults.  One object, serialised into the project file.
:class:`NodeStyle`
    Sparse per-node overrides, stored as a plain dict on ``Node.style`` so that
    a tree with three coloured clades does not pay for 200 000 style objects.

:func:`resolve` merges them, walking ancestors so that colouring a clade
colours everything beneath it without touching a single descendant.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from .color import Color, parse_color

__all__ = ["Theme", "NodeStyle", "NODE_STYLE_KEYS", "resolve", "LIGHT", "DARK"]


@dataclass(slots=True)
class NodeStyle:
    """Per-node overrides.  Every field is optional; ``None`` means inherit.

    ``*_inherited`` semantics: branch colour, width and dash propagate to
    descendants unless a descendant overrides them.  Label and marker settings
    apply only to the node that carries them.
    """

    branch_color: Color | None = None
    branch_width: float | None = None
    branch_dash: tuple[float, ...] | None = None
    branch_opacity: float | None = None

    label_color: Color | None = None
    label_size: float | None = None
    label_bold: bool | None = None
    label_italic: bool | None = None
    label_background: Color | None = None
    label_text: str | None = None
    """Display text overriding ``Node.name`` without changing the data."""
    label_hidden: bool | None = None

    marker_shape: str | None = None
    """One of the shapes in :data:`makeyourtree.tracks.shapes.SHAPES`."""
    marker_size: float | None = None
    marker_color: Color | None = None
    marker_stroke: Color | None = None

    clade_fill: Color | None = None
    """Background wash behind the whole subtree."""
    clade_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if v is None:
                continue
            out[f.name] = v.hex if isinstance(v, Color) else v
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NodeStyle":
        kw: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in d:
                continue
            v = d[f.name]
            kw[f.name] = parse_color(v) if f.name.endswith(("color", "fill", "background", "stroke")) and v is not None else v
        return cls(**kw)


NODE_STYLE_KEYS: frozenset[str] = frozenset(f.name for f in fields(NodeStyle))
"""Valid keys for ``Node.style``.  Loaders validate against this."""

INHERITED_KEYS: frozenset[str] = frozenset(
    {"branch_color", "branch_width", "branch_dash", "branch_opacity", "clade_fill"}
)
"""Keys that flow down to descendants."""


@dataclass(slots=True)
class Theme:
    """Document-wide visual defaults."""

    name: str = "MakeYourTree Light"

    # ---- page ---------------------------------------------------------
    background: Color = field(default_factory=lambda: Color(255, 255, 255))
    foreground: Color = field(default_factory=lambda: Color(24, 24, 27))
    muted: Color = field(default_factory=lambda: Color(113, 113, 122))
    accent: Color = field(default_factory=lambda: Color(37, 99, 235))

    # ---- branches -----------------------------------------------------
    branch_color: Color = field(default_factory=lambda: Color(51, 51, 58))
    branch_width: float = 1.2
    branch_cosmetic: bool = True
    """Keep branch strokes a constant on-screen width while zooming."""

    # ---- labels -------------------------------------------------------
    font_family: str = "Inter, Segoe UI, DejaVu Sans, sans-serif"
    label_size: float = 11.0
    label_color: Color | None = None
    """``None`` follows ``foreground``."""
    internal_label_size: float = 9.0
    internal_label_color: Color | None = None

    # ---- support values -----------------------------------------------
    show_support: bool = False
    support_size: float = 8.0
    support_color: Color = field(default_factory=lambda: Color(120, 113, 108))
    support_min: float | None = None
    """Hide support values below this threshold entirely."""
    support_format: str = "{:.3g}"
    support_position: str = "above"
    """``above``, ``below``, or ``node`` (a sized marker instead of text)."""

    # ---- guides and decorations ---------------------------------------
    guide_color: Color = field(default_factory=lambda: Color(203, 213, 225))
    guide_width: float = 0.6
    guide_dash: tuple[float, ...] = (1.0, 3.0)

    scalebar_show: bool = True
    scalebar_color: Color = field(default_factory=lambda: Color(82, 82, 91))
    scalebar_size: float = 9.0

    axis_show: bool = False
    axis_color: Color = field(default_factory=lambda: Color(228, 228, 231))

    collapse_fill: Color = field(default_factory=lambda: Color(148, 163, 184, 160))
    collapse_stroke: Color = field(default_factory=lambda: Color(71, 85, 105))

    # ---- interaction (canvas only, never exported) ---------------------
    selection_color: Color = field(default_factory=lambda: Color(37, 99, 235))
    selection_width: float = 2.6
    hover_color: Color = field(default_factory=lambda: Color(37, 99, 235, 90))
    search_hit_color: Color = field(default_factory=lambda: Color(234, 179, 8))

    # ---- tracks -------------------------------------------------------
    track_gap: float = 8.0
    """Band-space gap inserted between consecutive tracks."""
    track_margin: float = 14.0
    """Gap between the tip labels and the first track."""
    track_title_size: float = 10.0
    track_border: Color | None = None
    grid_color: Color = field(default_factory=lambda: Color(226, 232, 240))

    # ---- legend -------------------------------------------------------
    legend_show: bool = True
    legend_position: str = "right"
    """``right``, ``bottom``, ``top-left``, or ``none``."""
    legend_size: float = 10.0
    legend_swatch: float = 12.0
    legend_gap: float = 6.0

    # ---- palettes -----------------------------------------------------
    categorical_palette: str = "okabe-ito"
    sequential_palette: str = "viridis"
    diverging_palette: str = "blue-red"

    def effective_label_color(self) -> Color:
        return self.label_color or self.foreground

    def effective_internal_label_color(self) -> Color:
        return self.internal_label_color or self.muted

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, Color):
                out[f.name] = v.hex
            elif isinstance(v, tuple):
                out[f.name] = list(v)
            else:
                out[f.name] = v
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Theme":
        kw: dict[str, Any] = {}
        types = {f.name: f.type for f in fields(cls)}
        for k, v in d.items():
            if k not in types:
                continue
            ann = str(types[k])
            if v is None:
                kw[k] = None
            elif "Color" in ann:
                kw[k] = parse_color(v)
            elif "tuple" in ann and isinstance(v, list):
                kw[k] = tuple(v)
            else:
                kw[k] = v
        return cls(**kw)


def resolve(node, theme: Theme) -> dict[str, Any]:
    """Effective style for *node*: theme defaults, then inherited ancestor
    overrides, then the node's own overrides.

    Walks from the root down so that nearer ancestors win.  O(depth).
    """
    eff: dict[str, Any] = {
        "branch_color": theme.branch_color,
        "branch_width": theme.branch_width,
        "branch_dash": None,
        "branch_opacity": 1.0,
        "label_color": theme.effective_label_color(),
        "label_size": theme.label_size,
        "label_bold": False,
        "label_italic": False,
        "clade_fill": None,
    }
    chain = []
    cur = node
    while cur is not None:
        if cur.style:
            chain.append(cur.style)
        cur = cur.parent
    for st in reversed(chain):
        inherited = st is not node.style
        for k, v in st.items():
            if inherited and k not in INHERITED_KEYS:
                continue
            eff[k] = v
    return eff


LIGHT = Theme()

DARK = Theme(
    name="MakeYourTree Dark",
    background=Color(17, 17, 20),
    foreground=Color(240, 240, 245),
    muted=Color(150, 150, 160),
    branch_color=Color(214, 214, 222),
    guide_color=Color(70, 70, 80),
    axis_color=Color(55, 55, 64),
    grid_color=Color(48, 48, 56),
    support_color=Color(160, 160, 172),
    scalebar_color=Color(200, 200, 210),
    collapse_fill=Color(100, 116, 139, 170),
    collapse_stroke=Color(203, 213, 225),
)

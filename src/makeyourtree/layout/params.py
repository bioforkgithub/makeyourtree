# SPDX-License-Identifier: MIT
"""Layout parameters.

Every layout in MakeYourTree reduces to two INDEPENDENT coordinate assignments:

* a **cross** coordinate -- ``y`` in linear modes, ``angle`` in polar modes --
  derived purely from the left-to-right order of visible tips, and
* an **along** coordinate -- ``x`` in linear modes, ``radius`` in polar modes --
  derived purely from branch length or topological depth.

This separation is the central architectural invariant.  Reordering children
(ladderize, rotate) changes only the cross coordinate; rescaling or switching
between phylogram and cladogram changes only the along coordinate.  Both can
therefore be recomputed independently, which is what makes interactive
rotation and zooming cheap.

The unrooted layouts are the one exception: they place nodes in the plane
directly and expose ``x``/``y`` without a meaningful cross/along split.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class LayoutMode(str, enum.Enum):
    """How the tree is arranged in the plane."""

    RECTANGULAR = "rectangular"
    """Elbow edges: a radial segment plus a perpendicular connector."""
    SLANTED = "slanted"
    """One straight segment per edge, parent corner to child corner."""
    CIRCULAR = "circular"
    """Fan: tips equally spaced on angle, radius from length or depth."""
    RADIAL = "radial"
    """Circular cladogram: all tips land on the outer ring."""
    UNROOTED = "unrooted"
    """Equal-angle or equal-daylight; no root is implied by the drawing."""

    @property
    def is_polar(self) -> bool:
        return self in (LayoutMode.CIRCULAR, LayoutMode.RADIAL)

    @property
    def is_linear(self) -> bool:
        return self in (LayoutMode.RECTANGULAR, LayoutMode.SLANTED)


class BranchMode(str, enum.Enum):
    """How the along coordinate is derived."""

    PHYLOGRAM = "phylogram"
    """Along coordinate is cumulative branch length.  Honours the data."""
    CLADOGRAM_ALIGNED = "cladogram-aligned"
    """Branch lengths ignored; every visible tip is flush at the far edge."""
    CLADOGRAM_LEVEL = "cladogram-level"
    """Branch lengths ignored; along coordinate is the node's level."""

    @property
    def uses_lengths(self) -> bool:
        return self is BranchMode.PHYLOGRAM


class ParentRule(str, enum.Enum):
    """Where an internal node sits on the cross axis relative to its children.

    All three agree on strictly binary trees; they differ only at polytomies.
    """

    MIDPOINT = "midpoint"
    """Halfway between the first and last child.  Depends only on the tip span,
    so it is invariant under reordering within the subtree -- which is what
    makes incremental rotation cheap.  The default."""
    MEAN = "mean"
    """Arithmetic mean of all child cross coordinates."""
    WEIGHTED = "weighted"
    """Mean of child cross coordinates weighted by descendant tip count."""


class UnrootedMethod(str, enum.Enum):
    EQUAL_ANGLE = "equal-angle"
    EQUAL_DAYLIGHT = "equal-daylight"


class CollapseShape(str, enum.Enum):
    TRIANGLE = "triangle"
    """Apex at the clade's attachment point, base spanning its rows."""
    TRAPEZOID = "trapezoid"
    """Like a triangle but with the base clipped at min and max tip depth."""
    BAR = "bar"
    """A plain rectangle spanning the clade's rows."""


class CollapseRows(str, enum.Enum):
    """How many tip rows a collapsed clade consumes."""

    FIXED = "fixed"
    SQRT = "sqrt"
    PROPORTIONAL = "proportional"
    LOG = "log"


@dataclass(slots=True)
class LayoutParams:
    """Everything the layout engine needs that is not in the tree itself.

    Sizes are in scene units, which are CSS-like px: 1 unit is one point at
    100 % zoom, and export scales them.  ``None`` for a scale means "fit".
    """

    mode: LayoutMode = LayoutMode.RECTANGULAR
    branch_mode: BranchMode = BranchMode.PHYLOGRAM
    parent_rule: ParentRule = ParentRule.MIDPOINT

    # ---- extent -------------------------------------------------------
    width: float = 900.0
    """Along-axis extent available to the tree body, excluding labels and tracks."""
    height: float | None = None
    """Cross-axis extent.  ``None`` means derive it from ``row_spacing``."""
    row_spacing: float = 16.0
    """Cross-axis distance between adjacent tip rows."""
    x_scale: float | None = None
    """Scene units per unit of branch length.  ``None`` fits ``width``."""
    margin: float = 24.0

    # ---- linear -------------------------------------------------------
    align_tips: bool = False
    """Extend every tip to the far edge and draw a guide line to its label."""
    guide_lines: bool = True
    """Draw dotted guides when ``align_tips`` is on."""

    # ---- polar --------------------------------------------------------
    start_angle: float = -90.0
    """Degrees; -90 puts the seam at 12 o'clock.  0 is 3 o'clock."""
    arc: float = 350.0
    """Total sweep in degrees.  Values below 360 leave a wedge open."""
    inner_radius: float = 0.10
    """Hole at the centre, as a fraction of the outer radius."""
    direction: int = 1
    """+1 sweeps clockwise in scene coordinates, -1 anticlockwise."""
    rotate_labels: bool = True
    """Rotate tip labels to follow the radius, flipping on the left half."""

    # ---- unrooted -----------------------------------------------------
    unrooted_method: UnrootedMethod = UnrootedMethod.EQUAL_DAYLIGHT
    daylight_iterations: int = 3
    daylight_tolerance: float = 0.005

    # ---- collapsed clades ---------------------------------------------
    collapse_shape: CollapseShape = CollapseShape.TRIANGLE
    collapse_rows_mode: CollapseRows = CollapseRows.SQRT
    collapse_rows: float = 2.0
    """Row count for FIXED, or the coefficient for SQRT / LOG / PROPORTIONAL."""
    collapse_rows_max: float = 12.0

    # ---- labels -------------------------------------------------------
    show_tip_labels: bool = True
    show_internal_labels: bool = False
    tip_label_gap: float = 6.0
    """Gap between the tip point and the start of its label."""
    max_label_width: float | None = None
    """Clip labels wider than this, with an ellipsis.  ``None`` never clips."""

    # ---- misc ---------------------------------------------------------
    ignore_negative_lengths: bool = True
    """Clamp negative branch lengths to zero for drawing.  The data is untouched."""
    min_branch_length: float = 0.0
    """Floor applied to drawn lengths so zero-length edges stay clickable."""
    extra: dict = field(default_factory=dict)
    """Layout-specific escape hatch; never read by the shared contract."""

    # ------------------------------------------------------------------

    def replace(self, **kw) -> "LayoutParams":
        """Return a copy with *kw* overridden."""
        import dataclasses
        return dataclasses.replace(self, **kw)

    @property
    def arc_radians(self) -> float:
        import math
        return math.radians(self.arc)

    @property
    def start_radians(self) -> float:
        import math
        return math.radians(self.start_angle)

    def rows_for_collapsed(self, n_leaves: int) -> float:
        """Row budget for a collapsed clade containing *n_leaves* leaves."""
        import math
        m = self.collapse_rows_mode
        if m is CollapseRows.FIXED:
            v = self.collapse_rows
        elif m is CollapseRows.SQRT:
            v = self.collapse_rows * math.sqrt(max(1, n_leaves))
        elif m is CollapseRows.LOG:
            v = self.collapse_rows * (1.0 + math.log10(max(1, n_leaves)))
        else:
            v = float(max(1, n_leaves))
        return max(1.0, min(v, self.collapse_rows_max))

# SPDX-License-Identifier: MIT
"""What the along axis actually ended up encoding.

:class:`~makeyourtree.layout.params.BranchMode` records what the *user asked for*.
It is not always what the layout could deliver, and three consumers -- the
scale bar, the axis tick ladder and the collapsed-clade glyph -- are wrong,
sometimes dangerously wrong, if they trust the request instead of the result:

* ``RADIAL`` is defined by its tips forming a ring, so it ignores
  ``branch_mode`` entirely and lays the along axis out topologically.  Asking
  for ``RADIAL`` *and* ``PHYLOGRAM`` therefore yields ``frame.scale == 1.0``
  while ``params.branch_mode.uses_lengths`` is still true.  A scale bar built
  from that pair reads "500 substitutions/site" across a tree whose deepest
  tip is at 0.7 -- a figure that lies about the data.
* A phylogram whose file carries no branch lengths degenerates to every node
  stacked on the root.  There is no length for a bar to measure.
* A collapsed-clade glyph sized from tip depths at ``scale == 1.0`` collapses
  to a sliver a fraction of a pixel wide.

So every layout publishes the rule it *realised* under
:data:`ALONG_METADATA_KEY`, and every consumer asks here rather than
re-deriving it.  One vocabulary, one place to change it, and a layout that
cannot deliver lengths can say so instead of leaving the compositor to guess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .params import BranchMode, LayoutParams

if TYPE_CHECKING:  # pragma: no cover
    from ..core.node import Node
    from .frame import LayoutFrame

__all__ = ["ALONG_METADATA_KEY", "ALONG_LENGTH", "ALONG_LEVEL", "ALONG_ALIGNED",
           "NEGATIVE_METADATA_KEY", "along_rule", "along_is_length",
           "count_negative_lengths"]

ALONG_METADATA_KEY = "along"
""":attr:`LayoutFrame.metadata` key holding the realised rule."""

ALONG_LENGTH = "length"
"""Along coordinate is cumulative branch length; ``frame.scale`` is scene
units per unit of length and a scale bar is meaningful."""

ALONG_LEVEL = "level"
"""Along coordinate is the node's topological level."""

ALONG_ALIGNED = "aligned"
"""Along coordinate places every visible tip flush at the far edge."""


NEGATIVE_METADATA_KEY = "negative_lengths_clamped"
""":attr:`LayoutFrame.metadata` key holding how many visible edges had a
negative length that the drawing flattened to zero.

Layouts are handed no diagnostic sink -- ``compute(tree, params, metrics)`` is
the whole signature, and :class:`~makeyourtree.layout.frame.LayoutFrame` is a
frozen contract -- so a layout that needs to tell the compositor something
publishes it here.  ``band_space`` already works this way; this follows it.
"""


def count_negative_lengths(root: "Node") -> int:
    """Visible edges whose stored length is below zero.

    Counted over the *visible* tree because that is what gets drawn: a negative
    length inside a collapsed clade is not flattened on screen and reporting it
    would send the user looking for something they cannot see.  Iterative, like
    everything that walks a tree here -- a caterpillar phylogeny is deeper than
    CPython's recursion limit.
    """
    from ..core.traversal import preorder

    return sum(1 for n in preorder(root, visible_only=True)
               if n.parent is not None and (n.branch_length or 0.0) < 0.0)


def along_rule(frame: "LayoutFrame", params: LayoutParams | None = None) -> str:
    """The rule *frame* actually realised: length, level or aligned.

    A layout that published :data:`ALONG_METADATA_KEY` is believed.  For one
    that did not, the rule is inferred from the requested branch mode and from
    ``frame.scale``, which a length-based pass sets to something other than the
    cladogram sentinel of ``1.0`` -- and to ``0.0`` when the tree turned out to
    carry no usable lengths at all.
    """
    recorded = frame.metadata.get(ALONG_METADATA_KEY)
    if isinstance(recorded, str) and recorded:
        return recorded
    mode = (params or frame.params).branch_mode
    if mode is BranchMode.CLADOGRAM_LEVEL:
        return ALONG_LEVEL
    if mode is BranchMode.CLADOGRAM_ALIGNED:
        return ALONG_ALIGNED
    return ALONG_LENGTH if frame.scale > 0.0 else ALONG_ALIGNED


def along_is_length(frame: "LayoutFrame", params: LayoutParams | None = None) -> bool:
    """True when the along coordinate is proportional to branch length.

    The scale check is part of the answer, not a separate guard: a layout may
    report ``length`` and still have nothing to scale by (a star tree), and a
    consumer that only asked about the rule would divide by zero or draw a bar
    of infinite length.
    """
    import math
    if along_rule(frame, params) != ALONG_LENGTH:
        return False
    return frame.scale > 0.0 and math.isfinite(frame.scale)

# SPDX-License-Identifier: MIT
"""Layout engine: tree topology to scene coordinates."""
from .frame import Bounds, LayoutFrame, NodeCoord
from .params import (BranchMode, CollapseRows, CollapseShape, LayoutMode,
                     LayoutParams, ParentRule, UnrootedMethod)
from .projector import LinearProjector, PolarProjector, Projector, TextPlacement

__all__ = ["compute_layout", "LayoutFrame", "NodeCoord", "Bounds", "LayoutParams",
           "LayoutMode", "BranchMode", "ParentRule", "UnrootedMethod",
           "CollapseShape", "CollapseRows", "Projector", "LinearProjector",
           "PolarProjector", "TextPlacement"]


def compute_layout(tree, params=None, metrics=None):
    """Lay *tree* out and return a :class:`LayoutFrame`.

    Dispatches on ``params.mode``.  Implementations are imported lazily so that
    importing :mod:`makeyourtree.layout` stays cheap and so the three layout
    families stay independently testable.
    """
    from ..text.metrics import default_metrics
    params = params or LayoutParams()
    metrics = metrics or default_metrics()
    mode = params.mode
    if mode in (LayoutMode.RECTANGULAR, LayoutMode.SLANTED):
        from .linear import LinearLayout
        return LinearLayout().compute(tree, params, metrics)
    if mode in (LayoutMode.CIRCULAR, LayoutMode.RADIAL):
        from .polar import PolarLayout
        return PolarLayout().compute(tree, params, metrics)
    if mode is LayoutMode.UNROOTED:
        from .unrooted import UnrootedLayout
        return UnrootedLayout().compute(tree, params, metrics)
    raise ValueError(f"unsupported layout mode {mode!r}")

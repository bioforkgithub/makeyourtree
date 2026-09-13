# SPDX-License-Identifier: MIT
"""The interactive canvas: Qt painting, layer items, camera and hit-testing.

Import order matters only in that everything here depends on the core render
contract and nothing in the core may depend on any of it.  The public surface is
small on purpose: the rest of the application talks to :class:`TreeCanvas` and to
the session, never to the items or the backend directly.
"""

from __future__ import annotations

from .interaction import CanvasInteractor, HitTester, active_frame, scene_origin
from .layers import OverlayLayerItem, SceneLayerItem
from .qt_backend import QtBackend, arc_to_qt, build_path
from .qt_metrics import QtMetrics
from .view import TreeCanvas

__all__ = ["TreeCanvas", "QtBackend", "QtMetrics", "SceneLayerItem",
           "OverlayLayerItem", "CanvasInteractor", "HitTester", "active_frame",
           "scene_origin", "arc_to_qt", "build_path"]

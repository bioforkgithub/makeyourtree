# SPDX-License-Identifier: MIT
"""Shared helpers for the annotation and project-file tests."""

from __future__ import annotations

from typing import Any


from makeyourtree.core.traversal import preorder
from makeyourtree.core.tree import Tree
from makeyourtree.tracks import base as track_base


class ProbeTrack(track_base.Track):
    """A track that draws nothing, so that binding and serialisation can be
    tested without depending on any particular built-in track's option schema."""

    type_id = "test-probe"
    display_name = "Probe"

    @classmethod
    def default_options(cls) -> dict[str, Any]:
        opts = super().default_options()
        opts.update({"shape": "square", "border": {"width": 0.0}})
        return opts

    def measure(self, ctx) -> float:
        return float(self.opt("thickness", 22.0))

    def draw(self, ctx, sink) -> None:
        return None


def node_ids(tree: Tree) -> dict[str, int]:
    return {n.name: n.id for n in preorder(tree.root) if n.name}

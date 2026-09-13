# SPDX-License-Identifier: MIT
"""The document: a tree, how it is drawn, and everything hung off it.

A :class:`Document` is what gets saved, loaded, rendered and edited.  It owns
the tree, the layout parameters, the theme, the ordered track stack and any
named views.

Project file format (``.mytree``)
-------------------------------
A ZIP container.  A ZIP rather than one JSON blob because annotation data can
be large and binary (images), and because a container lets a user unzip a
project and diff the tree on its own::

    project.json      manifest: version, layout params, theme, track stack,
                      node style overrides, collapsed set, named views
    tree.nwk          the tree, as Extended Newick with node ids preserved
    tracks/<id>.json  one file per track: columns, rows, options
    assets/<name>     images and other binary payloads, referenced by track
                      options as ``asset:<name>``

``project.json`` carries ``"format": "makeyourtree-project"`` and an integer
``"version"``.  Readers must reject a version they do not know rather than
guessing, and writers must never silently drop fields they did not understand
-- unknown keys round-trip through ``Document.unknown`` so that a file written
by a newer build survives a load-and-save by an older one.

A flat single-file variant (``.mytree.json``) holds the same manifest with the
tree inlined as a string and tracks inlined as a list.  It exists for version
control and for piping through the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from ..core.tree import Tree
from ..layout.params import LayoutParams
from ..style.theme import Theme
from ..tracks.base import Track

__all__ = ["Document", "NamedView", "FORMAT_ID", "FORMAT_VERSION"]

FORMAT_ID = "makeyourtree-project"
FORMAT_VERSION = 1


@dataclass(slots=True)
class NamedView:
    """A saved camera plus layout state the user can jump back to."""

    name: str
    params: dict[str, Any] = field(default_factory=dict)
    """Serialised :class:`~makeyourtree.layout.params.LayoutParams` overrides."""
    center: tuple[float, float] | None = None
    zoom: float | None = None
    collapsed: list[int] = field(default_factory=list)
    note: str = ""


@dataclass(slots=True)
class Document:
    """Everything needed to reproduce a figure."""

    tree: Tree
    params: LayoutParams = field(default_factory=LayoutParams)
    theme: Theme = field(default_factory=Theme)
    tracks: list[Track] = field(default_factory=list)
    views: list[NamedView] = field(default_factory=list)

    title: str = ""
    path: str | None = None
    """Where this document was last saved.  ``None`` for an unsaved document."""
    source_path: str | None = None
    """Where the tree was originally imported from."""
    metadata: dict[str, Any] = field(default_factory=dict)
    unknown: dict[str, Any] = field(default_factory=dict)
    """Fields from a newer format version, preserved verbatim on save."""

    # ------------------------------------------------------------- tracks

    def add_track(self, track: Track, index: int | None = None) -> Track:
        if index is None:
            self.tracks.append(track)
        else:
            self.tracks.insert(index, track)
        return track

    def remove_track(self, track_or_id: Track | str) -> Track | None:
        tid = track_or_id if isinstance(track_or_id, str) else track_or_id.id
        for i, t in enumerate(self.tracks):
            if t.id == tid:
                return self.tracks.pop(i)
        return None

    def track(self, track_id: str) -> Track | None:
        for t in self.tracks:
            if t.id == track_id:
                return t
        return None

    def move_track(self, track_id: str, new_index: int) -> None:
        t = self.remove_track(track_id)
        if t is not None:
            self.tracks.insert(max(0, min(new_index, len(self.tracks))), t)

    def visible_tracks(self) -> list[Track]:
        return [t for t in self.tracks if t.visible]

    def __iter__(self) -> Iterator[Track]:
        return iter(self.tracks)

    # -------------------------------------------------------------- views

    def save_view(self, name: str, **kw: Any) -> NamedView:
        import dataclasses
        for v in self.views:
            if v.name == name:
                self.views.remove(v)
                break
        params = {f.name: getattr(self.params, f.name)
                  for f in dataclasses.fields(self.params)}
        params = {k: (v.value if hasattr(v, "value") else v) for k, v in params.items()
                  if not isinstance(v, dict)}
        view = NamedView(name=name, params=params,
                         collapsed=[n.id for n in self.tree.collapsed_nodes()], **kw)
        self.views.append(view)
        return view

    # ------------------------------------------------------ serialisation

    def manifest(self, *, inline_tree: bool = False) -> dict[str, Any]:
        """The ``project.json`` payload, minus the per-track files."""
        import dataclasses

        def enc(v: Any) -> Any:
            if hasattr(v, "value") and hasattr(v, "name"):   # enum
                return v.value
            if isinstance(v, tuple):
                return list(v)
            return v

        from ..tracks.base import _jsonable

        params = {f.name: enc(getattr(self.params, f.name))
                  for f in dataclasses.fields(self.params)}
        # Node styles hold Color objects; they must land in the manifest as hex.
        node_styles = {str(n.id): _jsonable(n.style)
                       for n in self.tree.nodes if n.style}
        out: dict[str, Any] = dict(self.unknown)
        out.update({
            "format": FORMAT_ID,
            "version": FORMAT_VERSION,
            "title": self.title,
            "source_path": self.source_path,
            "params": params,
            "theme": self.theme.to_dict(),
            "tracks": [t.id for t in self.tracks],
            "track_order": [t.id for t in self.tracks],
            "node_styles": node_styles,
            "collapsed": [n.id for n in self.tree.collapsed_nodes()],
            "hidden": [n.id for n in self.tree.nodes if n.hidden],
            "rooted": self.tree.rooted,
            "views": [
                {"name": v.name, "params": v.params, "center": list(v.center) if v.center else None,
                 "zoom": v.zoom, "collapsed": v.collapsed, "note": v.note}
                for v in self.views
            ],
            "metadata": self.metadata,
        })
        if inline_tree:
            out["tree"] = self.tree.to_newick(node_ids=True)
            out["track_data"] = [t.to_dict() for t in self.tracks]
        return out

    def __repr__(self) -> str:
        return (f"<Document {self.title or self.path or 'untitled'!r} "
                f"leaves={self.tree.n_leaves} tracks={len(self.tracks)}>")

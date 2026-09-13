# SPDX-License-Identifier: MIT
"""Reading and writing the ``.mytree`` project container.

The layout of the container is specified in :mod:`makeyourtree.doc.document`; this
module implements it.  Three concerns shape the code.

*Durability.*  A save never truncates the file the user already has.  Everything
is written to a temporary file in the target directory and then moved into place
with :func:`os.replace`, which is atomic on POSIX and on Windows (``MoveFileEx``
with ``MOVEFILE_REPLACE_EXISTING``).  A crash mid-save therefore leaves either
the old project or an abandoned temporary file, never a half-written project.

*Forward compatibility.*  Manifest keys this build does not know are copied into
:attr:`Document.unknown` and written back out unchanged, so opening a project in
an older build and saving it does not amputate it.  A major version we cannot
read is refused outright rather than guessed at.

*Distrust.*  A ``.mytree`` arrives by email and by download, so it is treated as
hostile input.  Entry names are validated against path traversal even though
nothing is extracted to disk, the entry count and total uncompressed size are
capped against a decompression bomb (the classic *zip of death*), and the
payload is JSON parsed with :mod:`json` -- never evaluated.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import re
import tempfile
import zipfile
from typing import Any, Callable, Iterable

from ..core.errors import FormatError
from ..core.tree import Tree
from ..layout.params import (BranchMode, CollapseRows, CollapseShape, LayoutMode,
                             LayoutParams, ParentRule, UnrootedMethod)
from ..style.color import Color
from ..style.theme import NodeStyle, Theme
from ..tracks.base import Track
from .document import FORMAT_ID, FORMAT_VERSION, Document, NamedView

__all__ = ["save_project", "load_project"]

MANIFEST_NAME = "project.json"
TREE_NAME = "tree.nwk"
TRACK_DIR = "tracks/"
ASSET_DIR = "assets/"

MAX_ENTRIES = 4096
"""Entry-count cap.  A real project has one manifest, one tree, a handful of
tracks and its images; tens of thousands of entries is an attack or a mistake."""
MAX_TOTAL_BYTES = 64 * 1024 * 1024
"""Cap on total uncompressed bytes read from one container."""

_KNOWN_MANIFEST_KEYS = frozenset({
    "format", "version", "title", "source_path", "params", "theme", "tracks",
    "track_order", "node_styles", "collapsed", "hidden", "rooted", "views",
    "metadata", "tree", "track_data",
})

_ENUM_TYPES = (LayoutMode, BranchMode, ParentRule, UnrootedMethod, CollapseShape,
               CollapseRows)

RUNTIME_METADATA_KEYS = frozenset({"text_metrics"})
"""Metadata keys that hold a live object, never a saved value.

``compose()`` reads the text measurer out of ``document.metadata`` -- that is
the documented way an application injects real font metrics -- so any host that
measures text properly ends up with a ``TextMetrics`` instance sitting in the
metadata dict that :meth:`Document.manifest` serialises wholesale. It is not
JSON, it is not document state, and a saved copy would be meaningless to
whatever opens the file next. Dropped on write; the host re-injects it on load.
"""

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
_DRIVE = re.compile(r"^[A-Za-z]:")
_B64_PREFIX = "base64:"


# ----------------------------------------------------------------------- save


def save_project(doc: Document, path: str | os.PathLike[str], *,
                 flat: bool = False) -> None:
    """Write *doc* to *path*.

    With *flat* the single-file ``.mytree.json`` variant is written: the same
    manifest with the tree inlined and the tracks in a list, which is what
    version control and shell pipelines want.  Otherwise the ZIP container is
    written with deflate compression -- the manifest and the Newick string are
    highly redundant text and compress by roughly an order of magnitude.
    """
    target = os.fspath(path)
    if flat:
        payload = json.dumps(_manifest(doc, inline_tree=True), indent=2,
                             ensure_ascii=False, default=_json_default)
        _atomic_write(target, lambda tmp: _write_text(tmp, payload))
    else:
        _atomic_write(target, lambda tmp: _write_zip(doc, tmp))
    doc.path = target


def _write_text(tmp: str, payload: str) -> None:
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)


def _manifest(doc: Document, *, inline_tree: bool) -> dict:
    """The document's manifest with the runtime-only metadata removed.

    Copied rather than mutated in place: saving a project must not reach into
    the live document and take the metrics away from the compositor.
    """
    manifest = doc.manifest(inline_tree=inline_tree)
    metadata = manifest.get("metadata")
    if isinstance(metadata, dict) and RUNTIME_METADATA_KEYS & metadata.keys():
        manifest["metadata"] = {k: v for k, v in metadata.items()
                                if k not in RUNTIME_METADATA_KEYS}
    return manifest


def _write_zip(doc: Document, tmp: str) -> None:
    manifest = _manifest(doc, inline_tree=False)
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, ensure_ascii=False,
                                              default=_json_default))
        # node_ids=True so that styles, collapsed flags and track rows -- all of
        # which key on node id -- still refer to the same nodes after a reload.
        zf.writestr(TREE_NAME, doc.tree.to_newick(node_ids=True))
        used: set[str] = set()
        for track in doc.tracks:
            name = _unique(_safe_component(track.id or track.type_id), used)
            zf.writestr(f"{TRACK_DIR}{name}.json",
                        json.dumps(track.to_dict(), indent=2, ensure_ascii=False,
                                   default=_json_default))
        for name, payload in _assets(doc):
            zf.writestr(f"{ASSET_DIR}{name}", payload)


def _assets(doc: Document) -> Iterable[tuple[str, bytes]]:
    """Asset payloads to store, from ``doc.metadata["assets"]``.

    Assets live in the metadata rather than on the document because the
    manifest has to stay JSON-serialisable; a value is therefore either a
    ``base64:`` payload (what :func:`load_project` produces) or the path of a
    file to pull in.
    """
    assets = doc.metadata.get("assets")
    if not isinstance(assets, dict):
        return
    for raw_name, value in assets.items():
        name = _safe_component(str(raw_name))
        if not name:
            continue
        if isinstance(value, (bytes, bytearray)):
            yield name, bytes(value)
        elif isinstance(value, str) and value.startswith(_B64_PREFIX):
            try:
                yield name, base64.b64decode(value[len(_B64_PREFIX):], validate=True)
            except (ValueError, TypeError) as exc:
                raise FormatError(f"asset {raw_name!r} is not valid base64") from exc
        elif isinstance(value, str) and os.path.isfile(value):
            with open(value, "rb") as fh:
                yield name, fh.read()
        else:
            raise FormatError(f"asset {raw_name!r} is neither a base64 payload "
                              "nor a readable file")


def _atomic_write(target: str, write: Callable[[str], None]) -> None:
    directory = os.path.dirname(os.path.abspath(target)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".makeyourtree-", suffix=".tmp")
    os.close(fd)
    try:
        write(tmp)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _safe_component(name: str) -> str:
    """A single path component safe to place inside the container."""
    cleaned = _UNSAFE_NAME.sub("_", name).lstrip(".")
    return cleaned[:120]


def _unique(name: str, used: set[str]) -> str:
    candidate = name or "track"
    i = 2
    while candidate in used:
        candidate = f"{name}-{i}"
        i += 1
    used.add(candidate)
    return candidate


def _json_default(value: Any) -> Any:
    if isinstance(value, Color):
        return value.hex
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, (bytes, bytearray)):
        return _B64_PREFIX + base64.b64encode(bytes(value)).decode("ascii")
    raise TypeError(f"{type(value).__name__} is not JSON-serialisable")


# ----------------------------------------------------------------------- load


def load_project(path: str | os.PathLike[str]) -> Document:
    """Read a project written by :func:`save_project`, in either variant.

    The variant is decided by content, not by file name, so a ``.mytree`` that is
    really the flat JSON still opens.
    """
    target = os.fspath(path)
    if zipfile.is_zipfile(target):
        manifest, tree_text, tracks, assets = _read_zip(target)
    else:
        manifest = _read_flat(target)
        tree_text = manifest.get("tree")
        tracks = list(manifest.get("track_data") or [])
        assets = {}
        if not isinstance(tree_text, str):
            raise FormatError(f"{target}: not a MakeYourTree project "
                              "(no ZIP container and no inline tree)")

    _check_header(manifest, target)
    doc = _build(manifest, tree_text, tracks)
    if assets:
        doc.metadata.setdefault("assets", {}).update(assets)
    doc.path = target
    return doc


def _read_flat(target: str) -> dict[str, Any]:
    if os.path.getsize(target) > MAX_TOTAL_BYTES:
        raise FormatError(f"{target}: project file exceeds "
                          f"{MAX_TOTAL_BYTES} bytes")
    with open(target, "r", encoding="utf-8-sig") as fh:
        text = fh.read()
    try:
        manifest = json.loads(text)
    except ValueError as exc:
        raise FormatError(f"{target}: not a MakeYourTree project ({exc})") from None
    if not isinstance(manifest, dict):
        raise FormatError(f"{target}: project manifest is not an object")
    return manifest


def _read_zip(target: str) -> tuple[dict[str, Any], str, list[dict[str, Any]],
                                    dict[str, str]]:
    with zipfile.ZipFile(target) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise FormatError(f"{target}: {len(infos)} entries exceeds the "
                              f"limit of {MAX_ENTRIES}")
        declared = 0
        for info in infos:
            _check_entry_name(info.filename, target)
            declared += info.file_size
        if declared > MAX_TOTAL_BYTES:
            raise FormatError(f"{target}: declared uncompressed size "
                              f"{declared} exceeds the limit of {MAX_TOTAL_BYTES}")

        budget = MAX_TOTAL_BYTES
        manifest_raw, budget = _read_entry(zf, MANIFEST_NAME, budget, target)
        if manifest_raw is None:
            raise FormatError(f"{target}: no {MANIFEST_NAME} in the container")
        try:
            manifest = json.loads(manifest_raw.decode("utf-8"))
        except ValueError as exc:
            raise FormatError(f"{target}: {MANIFEST_NAME} is not valid JSON "
                              f"({exc})") from None
        if not isinstance(manifest, dict):
            raise FormatError(f"{target}: project manifest is not an object")

        tree_raw, budget = _read_entry(zf, TREE_NAME, budget, target)
        if tree_raw is None:
            raise FormatError(f"{target}: no {TREE_NAME} in the container")
        tree_text = tree_raw.decode("utf-8")

        tracks: list[dict[str, Any]] = []
        assets: dict[str, str] = {}
        for info in infos:
            name = info.filename
            if name.startswith(TRACK_DIR) and name.endswith(".json"):
                raw, budget = _read_entry(zf, name, budget, target)
                if raw is None:
                    continue
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except ValueError as exc:
                    raise FormatError(f"{target}: {name} is not valid JSON "
                                      f"({exc})") from None
                if isinstance(payload, dict):
                    tracks.append(payload)
            elif name.startswith(ASSET_DIR) and not name.endswith("/"):
                raw, budget = _read_entry(zf, name, budget, target)
                if raw is None:
                    continue
                assets[name[len(ASSET_DIR):]] = (
                    _B64_PREFIX + base64.b64encode(raw).decode("ascii"))
    return manifest, tree_text, tracks, assets


def _check_entry_name(name: str, target: str) -> None:
    """Refuse zip-slip names.

    Nothing here is extracted to disk, but a name that tries to escape the
    container is evidence of a hostile file, and the next reader of this data
    may well be one that does write it out.
    """
    if not name or name.startswith(("/", "\\")) or _DRIVE.match(name):
        raise FormatError(f"{target}: unsafe entry name {name!r}")
    if any(part in ("..", "") for part in re.split(r"[/\\]", name.rstrip("/"))):
        raise FormatError(f"{target}: unsafe entry name {name!r}")


def _read_entry(zf: zipfile.ZipFile, name: str, budget: int,
                target: str) -> tuple[bytes | None, int]:
    """Read one entry, refusing to spend more than *budget* bytes on it.

    The size in the ZIP directory is attacker-controlled, so the read itself is
    bounded as well: an entry whose real content outruns the header is a bomb
    with a forged manifest.
    """
    try:
        with zf.open(name) as fh:
            data = fh.read(budget + 1)
    except KeyError:
        return None, budget
    if len(data) > budget:
        raise FormatError(f"{target}: entry {name!r} exceeds the remaining "
                          f"size budget of {budget} bytes")
    return data, budget - len(data)


def _check_header(manifest: dict[str, Any], target: str) -> None:
    fmt = manifest.get("format")
    if fmt != FORMAT_ID:
        raise FormatError(f"{target}: not a MakeYourTree project "
                          f"(format={fmt!r}, expected {FORMAT_ID!r})")
    raw = manifest.get("version", FORMAT_VERSION)
    try:
        major = int(str(raw).split(".")[0])
    except ValueError:
        raise FormatError(f"{target}: unreadable project version {raw!r}") from None
    if major > FORMAT_VERSION:
        raise FormatError(
            f"{target}: project format version {major} was written by a newer "
            f"build of MakeYourTree; this build reads version {FORMAT_VERSION}")


def _build(manifest: dict[str, Any], tree_text: str,
           tracks: list[dict[str, Any]]) -> Document:
    tree = Tree.from_newick(tree_text)
    tree.rooted = bool(manifest.get("rooted", True))
    tree.refresh()

    doc = Document(
        tree=tree,
        params=_decode_params(manifest.get("params") or {}),
        theme=Theme.from_dict(manifest.get("theme") or {}),
        title=str(manifest.get("title") or ""),
        source_path=manifest.get("source_path"),
        metadata=dict(manifest.get("metadata") or {}),
    )
    doc.unknown = {k: v for k, v in manifest.items()
                   if k not in _KNOWN_MANIFEST_KEYS}

    for raw_id, style in (manifest.get("node_styles") or {}).items():
        node = tree.by_id(_as_int(raw_id))
        if node is not None and isinstance(style, dict):
            node.style = _decode_style(style) or None
    for raw_id in manifest.get("collapsed") or ():
        node = tree.by_id(_as_int(raw_id))
        if node is not None:
            node.collapsed = True
    for raw_id in manifest.get("hidden") or ():
        node = tree.by_id(_as_int(raw_id))
        if node is not None:
            node.hidden = True

    doc.tracks = _order_tracks(tracks, manifest.get("track_order")
                               or manifest.get("tracks") or [])
    doc.views = [_decode_view(v) for v in (manifest.get("views") or ())
                 if isinstance(v, dict)]
    return doc


def _order_tracks(payloads: list[dict[str, Any]],
                  order: list[Any]) -> list[Track]:
    """Rebuild the track stack in the order the manifest recorded.

    Tracks are matched to the order list by their own id rather than by file
    name, so a container whose track files were renamed by hand still loads in
    the right order.  Anything the order list does not mention keeps its
    original relative position at the end.
    """
    index_by_id: dict[str, int] = {}
    for i, payload in enumerate(payloads):
        tid = payload.get("id")
        if isinstance(tid, str) and tid:
            index_by_id.setdefault(tid, i)
    taken: set[int] = set()
    ordered: list[dict[str, Any]] = []
    for tid in order:
        i = index_by_id.get(str(tid))
        if i is not None and i not in taken:
            taken.add(i)
            ordered.append(payloads[i])
    ordered.extend(p for i, p in enumerate(payloads) if i not in taken)

    out: list[Track] = []
    for payload in ordered:
        try:
            out.append(Track.from_dict(payload))
        except KeyError as exc:
            raise FormatError(f"track {payload.get('id')!r}: "
                              f"{exc.args[0]}") from None
    return out


def _decode_view(d: dict[str, Any]) -> NamedView:
    center = d.get("center")
    return NamedView(
        name=str(d.get("name") or ""),
        params=dict(d.get("params") or {}),
        center=(float(center[0]), float(center[1]))
        if isinstance(center, (list, tuple)) and len(center) == 2 else None,
        zoom=d.get("zoom"),
        collapsed=[_as_int(x) for x in (d.get("collapsed") or ())],
        note=str(d.get("note") or ""),
    )


def _decode_params(d: dict[str, Any]) -> LayoutParams:
    """Rebuild :class:`LayoutParams`, turning stored strings back into enums.

    The field annotations are strings here (the module uses postponed
    evaluation), so the enum class is found by name rather than by identity.
    """
    fields = {f.name: str(f.type) for f in dataclasses.fields(LayoutParams)}
    kw: dict[str, Any] = {}
    for key, value in d.items():
        ann = fields.get(key)
        if ann is None:
            continue
        enum_cls = next((c for c in _ENUM_TYPES if c.__name__ in ann), None)
        if enum_cls is not None and value is not None:
            try:
                value = enum_cls(value)
            except ValueError:
                continue                    # keep the dataclass default
        kw[key] = value
    return LayoutParams(**kw)


def _decode_style(d: dict[str, Any]) -> dict[str, Any]:
    """Manifest style dict -> ``Node.style``, with colours as :class:`Color`.

    ``Node.style`` holds live objects because :func:`makeyourtree.style.theme.resolve`
    copies its values straight into the effective style.
    """
    style = NodeStyle.from_dict(d)
    out: dict[str, Any] = {}
    for f in dataclasses.fields(NodeStyle):
        v = getattr(style, f.name)
        if v is None:
            continue
        out[f.name] = tuple(v) if f.name == "branch_dash" and isinstance(v, list) else v
    return out


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1

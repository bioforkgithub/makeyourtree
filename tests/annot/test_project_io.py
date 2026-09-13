# SPDX-License-Identifier: MIT
"""The ``.mytree`` project container: round-tripping, forward compatibility, safety."""

from __future__ import annotations

import json
import os
import zipfile

import pytest

from makeyourtree.core.errors import FormatError
from makeyourtree.doc import Document, NamedView, load_project, save_project
from makeyourtree.doc.io import MAX_TOTAL_BYTES, _read_entry
from makeyourtree.layout.params import (BranchMode, CollapseRows, LayoutMode,
                                    LayoutParams, ParentRule)
from makeyourtree.style.color import Color
from makeyourtree.style.theme import DARK
from makeyourtree.tracks.base import TrackData
from _annot_support import ProbeTrack, node_ids


def _document(tree) -> Document:
    ids = node_ids(tree)
    tree.by_id(ids["A"]).style = {"branch_color": Color(255, 0, 0),
                                  "branch_width": 3.0,
                                  "branch_dash": (2.0, 1.0),
                                  "label_italic": True}
    tree.by_id(ids["CD"]).style = {"clade_fill": Color(0, 128, 255, 128)}
    tree.by_id(ids["CD"]).collapsed = True
    tree.by_id(ids["B"]).hidden = True

    params = LayoutParams(mode=LayoutMode.CIRCULAR,
                          branch_mode=BranchMode.CLADOGRAM_ALIGNED,
                          parent_rule=ParentRule.WEIGHTED,
                          collapse_rows_mode=CollapseRows.LOG,
                          arc=270.0, height=None, align_tips=True)
    doc = Document(tree=tree, params=params, theme=DARK, title="Figure 1",
                   source_path="/data/tree.nwk",
                   metadata={"author": "test", "notes": ["a", "b"]})
    doc.add_track(ProbeTrack(id="t-one", title="One",
                             data=TrackData(columns=["group"],
                                            rows={ids["A"]: ["Alpha"],
                                                  ids["B"]: [None]},
                                            source="one.mytrack"),
                             options={"thickness": 18.0}))
    doc.add_track(ProbeTrack(id="t-two", title="Two",
                             data=TrackData(columns=["x", "y"],
                                            rows={ids["C"]: [1, 2.5]})))
    doc.tracks[1].visible = False
    doc.views.append(NamedView(name="overview", params={"mode": "circular"},
                               center=(10.0, 20.0), zoom=1.5,
                               collapsed=[ids["CD"]], note="start here"))
    return doc


def _assert_same(loaded: Document, original: Document) -> None:
    assert loaded.title == original.title
    assert loaded.source_path == original.source_path
    assert loaded.metadata == original.metadata
    assert loaded.params == original.params
    assert loaded.theme.to_dict() == original.theme.to_dict()

    src_nodes = {n.id: n for n in original.tree.nodes}
    for node in loaded.tree.nodes:
        src = src_nodes[node.id]
        assert node.name == src.name
        assert node.branch_length == src.branch_length
        assert node.style == src.style
        assert node.collapsed == src.collapsed
        assert node.hidden == src.hidden
    assert len(loaded.tree.nodes) == len(src_nodes)
    assert loaded.tree.rooted == original.tree.rooted

    assert [t.id for t in loaded.tracks] == [t.id for t in original.tracks]
    for got, want in zip(loaded.tracks, original.tracks):
        assert type(got) is type(want)
        assert got.title == want.title
        assert got.visible == want.visible
        assert got.options == want.options
        assert got.data.columns == want.data.columns
        assert got.data.rows == want.data.rows
        assert got.data.source == want.data.source

    assert len(loaded.views) == len(original.views)
    for got, want in zip(loaded.views, original.views):
        assert (got.name, got.params, got.center, got.zoom, got.collapsed,
                got.note) == (want.name, want.params, want.center, want.zoom,
                              want.collapsed, want.note)


@pytest.mark.parametrize("flat", [False, True])
def test_save_and_load_reproduces_the_document(tree, tmp_path, flat):
    doc = _document(tree)
    path = tmp_path / ("project.mytree.json" if flat else "project.mytree")
    save_project(doc, path, flat=flat)
    _assert_same(load_project(path), doc)


def test_zip_container_layout(tree, tmp_path):
    doc = _document(tree)
    path = tmp_path / "project.mytree"
    save_project(doc, path)
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        assert {"project.json", "tree.nwk", "tracks/t-one.json",
                "tracks/t-two.json"} <= names
        assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in zf.infolist())
        manifest = json.loads(zf.read("project.json"))
        assert manifest["format"] == "makeyourtree-project"
        assert manifest["track_order"] == ["t-one", "t-two"]
        assert "(" in zf.read("tree.nwk").decode("utf-8")


def test_flat_variant_inlines_tree_and_tracks(tree, tmp_path):
    doc = _document(tree)
    path = tmp_path / "project.mytree.json"
    save_project(doc, path, flat=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["tree"].endswith(";")
    assert [t["id"] for t in payload["track_data"]] == ["t-one", "t-two"]


def test_node_ids_survive_the_round_trip(tree, tmp_path):
    doc = _document(tree)
    path = tmp_path / "project.mytree"
    save_project(doc, path)
    loaded = load_project(path)
    assert node_ids(loaded.tree) == node_ids(tree)


def test_layout_enums_come_back_as_enum_members(tree, tmp_path):
    """String enums compare equal to their values, so identity is what matters."""
    doc = _document(tree)
    path = tmp_path / "project.mytree"
    save_project(doc, path)
    params = load_project(path).params
    assert params.mode is LayoutMode.CIRCULAR
    assert params.branch_mode is BranchMode.CLADOGRAM_ALIGNED
    assert params.parent_rule is ParentRule.WEIGHTED
    assert params.collapse_rows_mode is CollapseRows.LOG
    assert params.arc == 270.0 and params.height is None


def test_unreadable_enum_value_falls_back_to_the_default(tmp_path):
    path = tmp_path / "odd.mytree.json"
    path.write_text(json.dumps({
        "format": "makeyourtree-project", "version": 1, "tree": "(A,B);",
        "params": {"mode": "hyperbolic", "row_spacing": 21.0, "bogus": 1},
    }), encoding="utf-8")
    params = load_project(path).params
    assert params.mode is LayoutMode.RECTANGULAR
    assert params.row_spacing == 21.0


def test_track_order_follows_the_manifest_not_the_file_names(tree, tmp_path):
    doc = _document(tree)
    doc.move_track("t-two", 0)
    path = tmp_path / "project.mytree"
    save_project(doc, path)
    assert [t.id for t in load_project(path).tracks] == ["t-two", "t-one"]


def test_saving_records_where_the_document_went(tree, tmp_path):
    doc = _document(tree)
    path = tmp_path / "project.mytree"
    save_project(doc, path)
    assert doc.path == str(path)
    assert load_project(path).path == str(path)


def test_unknown_manifest_keys_survive_load_and_save(tree, tmp_path):
    doc = _document(tree)
    doc.unknown = {"lighting": {"mode": "sunset"}, "future_count": 7}
    first = tmp_path / "a.mytree"
    save_project(doc, first)

    reloaded = load_project(first)
    assert reloaded.unknown == doc.unknown

    second = tmp_path / "b.mytree"
    save_project(reloaded, second)
    with zipfile.ZipFile(second) as zf:
        manifest = json.loads(zf.read("project.json"))
    assert manifest["lighting"] == {"mode": "sunset"}
    assert manifest["future_count"] == 7


def test_assets_round_trip_through_the_container(tree, tmp_path):
    doc = _document(tree)
    blob = tmp_path / "logo.png"
    blob.write_bytes(b"\x89PNG\r\n\x1a\n binary payload")
    doc.metadata["assets"] = {"logo.png": str(blob)}
    path = tmp_path / "project.mytree"
    save_project(doc, path)

    with zipfile.ZipFile(path) as zf:
        assert zf.read("assets/logo.png") == blob.read_bytes()
    loaded = load_project(path)
    assert loaded.metadata["assets"]["logo.png"].startswith("base64:")

    again = tmp_path / "again.mytree"
    save_project(loaded, again)
    with zipfile.ZipFile(again) as zf:
        assert zf.read("assets/logo.png") == blob.read_bytes()


# ------------------------------------------------------------------- refusals


def _minimal_manifest() -> str:
    return json.dumps({"format": "makeyourtree-project", "version": 1,
                       "params": {}, "theme": {}, "tracks": []})


def test_path_traversal_entry_is_rejected(tmp_path):
    path = tmp_path / "evil.mytree"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", _minimal_manifest())
        zf.writestr("tree.nwk", "(A,B);")
        zf.writestr("../../escaped.txt", "pwned")
    with pytest.raises(FormatError, match="unsafe entry name"):
        load_project(path)


def test_absolute_entry_name_is_rejected(tmp_path):
    path = tmp_path / "evil2.mytree"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", _minimal_manifest())
        zf.writestr("/etc/passwd", "pwned")
    with pytest.raises(FormatError, match="unsafe entry name"):
        load_project(path)


def test_decompression_bomb_is_rejected(tmp_path):
    path = tmp_path / "bomb.mytree"
    oversize = MAX_TOTAL_BYTES + (8 << 20)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", _minimal_manifest())
        with zf.open("assets/bomb.bin", "w") as fh:
            chunk = b"\0" * (1 << 20)
            for _ in range(oversize >> 20):
                fh.write(chunk)
    assert path.stat().st_size < (1 << 20)      # tiny on disk, huge when read
    with pytest.raises(FormatError, match="exceeds the limit"):
        load_project(path)


def test_entry_read_is_bounded_even_if_the_header_lies(tree, tmp_path):
    """The size budget is enforced on the bytes read, not on the declared size."""
    path = tmp_path / "project.mytree"
    save_project(_document(tree), path)
    with zipfile.ZipFile(path) as zf:
        with pytest.raises(FormatError, match="size budget"):
            _read_entry(zf, "tree.nwk", 2, str(path))


def test_too_many_entries_is_rejected(tmp_path, monkeypatch):
    import makeyourtree.doc.io as project_io
    monkeypatch.setattr(project_io, "MAX_ENTRIES", 3)
    path = tmp_path / "many.mytree"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", _minimal_manifest())
        for i in range(5):
            zf.writestr(f"assets/{i}.txt", "x")
    with pytest.raises(FormatError, match="exceeds the limit"):
        load_project(path)


def test_newer_major_version_is_refused(tmp_path):
    path = tmp_path / "future.mytree.json"
    path.write_text(json.dumps({"format": "makeyourtree-project", "version": 99,
                                "tree": "(A,B);"}), encoding="utf-8")
    with pytest.raises(FormatError, match="newer build"):
        load_project(path)


def test_foreign_json_is_refused(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"format": "something-else", "version": 1}),
                    encoding="utf-8")
    with pytest.raises(FormatError, match="not a MakeYourTree project"):
        load_project(path)


def test_zip_without_a_manifest_is_refused(tmp_path):
    path = tmp_path / "empty.mytree"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("readme.txt", "nothing to see")
    with pytest.raises(FormatError, match="no project.json"):
        load_project(path)


def test_zip_without_a_tree_is_refused(tmp_path):
    path = tmp_path / "treeless.mytree"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", _minimal_manifest())
    with pytest.raises(FormatError, match="no tree.nwk"):
        load_project(path)


def test_unknown_track_type_is_refused_rather_than_dropped(tree, tmp_path):
    doc = _document(tree)
    path = tmp_path / "project.mytree"
    save_project(doc, path)
    with zipfile.ZipFile(path) as zf:
        entries = {n: zf.read(n) for n in zf.namelist()}
    payload = json.loads(entries["tracks/t-one.json"])
    payload["type"] = "not-a-registered-track"
    entries["tracks/t-one.json"] = json.dumps(payload).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    with pytest.raises(FormatError, match="unknown track type"):
        load_project(path)


# ---------------------------------------------------------------- durability


def test_a_failed_save_leaves_the_previous_file_intact(tree, tmp_path):
    doc = _document(tree)
    path = tmp_path / "project.mytree"
    save_project(doc, path)
    before = path.read_bytes()

    doc.metadata["broken"] = object()        # not JSON-serialisable
    with pytest.raises(TypeError):
        save_project(doc, path)

    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["project.mytree"]


def test_save_into_a_missing_directory_raises(tree, tmp_path):
    with pytest.raises(OSError):
        save_project(_document(tree), tmp_path / "nope" / "project.mytree")


def test_oversized_flat_file_is_refused(tmp_path, monkeypatch):
    import makeyourtree.doc.io as project_io
    monkeypatch.setattr(project_io, "MAX_TOTAL_BYTES", 16)
    path = tmp_path / "big.mytree.json"
    path.write_text(_minimal_manifest(), encoding="utf-8")
    with pytest.raises(FormatError, match="exceeds"):
        load_project(path)


def test_load_project_accepts_path_like(tree, tmp_path):
    doc = _document(tree)
    path = tmp_path / "project.mytree"
    save_project(doc, os.fspath(path))
    assert load_project(path).title == "Figure 1"


# ------------------------------------------------------- runtime metadata


def test_a_live_text_measurer_in_the_metadata_does_not_break_saving(tree,
                                                                    tmp_path):
    """``compose()`` reads the measurer out of ``document.metadata``.

    Any host that measures text with real fonts therefore leaves a live
    ``TextMetrics`` object in the metadata dict that the manifest serialises
    wholesale -- which used to abort every save with "not JSON-serialisable",
    i.e. an application with working text metrics could not save at all.
    """
    from makeyourtree.text.metrics import CachedMetrics, FallbackMetrics

    metrics = CachedMetrics(FallbackMetrics())
    doc = _document(tree)
    doc.metadata["text_metrics"] = metrics

    for name, flat in (("p.mytree", False), ("p.mytree.json", True)):
        target = tmp_path / name
        save_project(doc, target, flat=flat)
        loaded = load_project(target)
        assert "text_metrics" not in loaded.metadata, (
            "a live measurer must not be written into the project file")
        assert loaded.metadata["author"] == "test", (
            "dropping the runtime key must not drop the real metadata")

    assert doc.metadata["text_metrics"] is metrics, (
        "saving must not take the measurer away from the live document")

# SPDX-License-Identifier: MIT
"""End-to-end CLI runs against temporary files.

Every subcommand must exit 0 on good input, exit non-zero with a one-line
message on bad input, and never leak a traceback for a user-facing failure.
"""
from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET

import pytest

from makeyourtree.cli import build_parser, main

pytest.importorskip("makeyourtree.io", reason="tree readers are not available yet")

SVG_NS = "{http://www.w3.org/2000/svg}"

NEWICK = "((Alpha:0.1,Beta:0.2)inner:0.3,(Gamma:0.4,Delta:0.55)other:0.6)root;"


@pytest.fixture
def tree_file(tmp_path):
    path = tmp_path / "sample.nwk"
    path.write_text(NEWICK + "\n", encoding="utf-8")
    return path


def run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_info_prints_a_summary(capsys, tree_file):
    code, out, _ = run(capsys, "info", str(tree_file))
    assert code == 0
    assert "leaves          4" in out
    assert "nodes           7" in out
    assert "format          newick" in out
    assert "rooted" in out


def test_info_json_is_machine_readable(capsys, tree_file):
    code, out, _ = run(capsys, "info", str(tree_file), "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["leaves"] == 4
    assert payload["nodes"] == 7
    assert payload["format"] == "newick"
    assert payload["has_branch_lengths"] is True
    assert isinstance(payload["diagnostics"], list)


def test_info_counts_negative_lengths_when_there_are_any(capsys, tmp_path):
    path = tmp_path / "neg.nwk"
    path.write_text("(Alpha:-0.5,Beta:1);", encoding="utf-8")
    code, out, err = run(capsys, "info", str(path))
    assert code == 0
    assert "negative lengths 1" in out
    assert "io.negative-branch-lengths" in err


def test_info_stays_silent_about_negative_lengths_when_there_are_none(capsys,
                                                                     tree_file):
    """A zero line on every ordinary tree teaches the reader to skip the block."""
    code, out, _ = run(capsys, "info", str(tree_file))
    assert "negative lengths" not in out


def test_info_warns_about_repeated_tip_names(capsys, tmp_path):
    path = tmp_path / "dup.nwk"
    path.write_text("(Alpha,Alpha,Beta);", encoding="utf-8")
    code, _, err = run(capsys, "info", str(path))
    assert code == 0
    assert "io.duplicate-tip-name" in err
    assert "'Alpha' (x2)" in err


def test_render_warns_that_it_flattened_negative_lengths(capsys, tmp_path):
    tree = tmp_path / "neg.nwk"
    tree.write_text("(Alpha:-0.5,Beta:1);", encoding="utf-8")
    out_path = tmp_path / "figure.svg"
    code, _, err = run(capsys, "render", str(tree), str(out_path))
    assert code == 0
    assert "layout.negative-lengths-clamped" in err


SUPPORT_LABELS = "((Alpha:0.1,Beta:0.2)95:0.3,(Gamma:0.4,Delta:0.5)72:0.6);"


@pytest.fixture
def support_file(tmp_path):
    path = tmp_path / "support.nwk"
    path.write_text(SUPPORT_LABELS + "\n", encoding="utf-8")
    return path


def test_a_numeric_internal_label_is_flagged_by_default(capsys, support_file):
    code, _, err = run(capsys, "info", str(support_file))
    assert code == 0
    assert "newick.internal-label-ambiguous" in err


def test_the_ambiguity_note_names_no_python_keyword(capsys, support_file):
    """The people who read this are at a terminal; they cannot pass a kwarg."""
    _, _, err = run(capsys, "info", str(support_file))
    assert "internal_labels=" not in err
    assert "internal labels set to 'name'" in err


@pytest.mark.parametrize("choice", ["name", "support"])
def test_choosing_how_to_read_internal_labels_settles_the_ambiguity(
        capsys, support_file, choice):
    code, _, err = run(capsys, "info", str(support_file),
                       "--internal-labels", choice)
    assert code == 0
    assert "newick.internal-label-ambiguous" not in err


def test_internal_labels_name_keeps_them_as_names(capsys, support_file):
    code, out, _ = run(capsys, "info", str(support_file),
                       "--internal-labels", "name", "--json")
    assert code == 0
    assert json.loads(out)["has_support"] is False


def test_internal_labels_support_reads_them_as_support(capsys, support_file):
    code, out, _ = run(capsys, "info", str(support_file),
                       "--internal-labels", "support", "--json")
    assert json.loads(out)["has_support"] is True


@pytest.mark.parametrize("command", ["info", "convert", "render", "reroot"])
def test_every_reading_command_offers_the_option(command):
    """A user who hits the note on `info` will hit it again on `render`."""
    parser = build_parser()
    sub = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    options = {s for action in sub.choices[command]._actions
               for s in action.option_strings}
    assert "--internal-labels" in options


def test_info_reports_parse_diagnostics_on_stderr(capsys, tmp_path):
    path = tmp_path / "nosemi.nwk"
    path.write_text("(A:1,B:2)", encoding="utf-8")
    code, out, err = run(capsys, "info", str(path), "--json")
    assert code == 0
    payload = json.loads(out)
    # A lenient reader opens the file; whatever it complained about is reported.
    assert payload["leaves"] == 2
    if payload["diagnostics"]:
        assert err.strip() != ""


def test_quiet_suppresses_diagnostics(capsys, tmp_path):
    path = tmp_path / "nosemi.nwk"
    path.write_text("(A:1,B:2)", encoding="utf-8")
    code, _, err = run(capsys, "--quiet", "info", str(path))
    assert code == 0
    assert err == ""


def test_info_on_a_missing_file_is_a_message_not_a_traceback(capsys, tmp_path):
    code, out, err = run(capsys, "info", str(tmp_path / "absent.nwk"))
    assert code != 0
    assert out == ""
    assert err.startswith("makeyourtree:")
    assert "Traceback" not in err


def test_convert_writes_the_requested_format(capsys, tree_file, tmp_path):
    out_path = tmp_path / "converted.nwk"
    code, _, _ = run(capsys, "convert", str(tree_file), str(out_path))
    assert code == 0
    text = out_path.read_text(encoding="utf-8")
    assert text.rstrip().endswith(";")
    assert "Alpha" in text and "Delta" in text


def test_convert_round_trips_through_the_reader(capsys, tree_file, tmp_path):
    out_path = tmp_path / "again.nwk"
    assert run(capsys, "convert", str(tree_file), str(out_path))[0] == 0
    code, out, _ = run(capsys, "info", str(out_path), "--json")
    assert code == 0
    assert json.loads(out)["leaves"] == 4


def test_convert_rejects_a_format_it_cannot_write(capsys, tree_file, tmp_path):
    code, _, err = run(capsys, "convert", str(tree_file),
                       str(tmp_path / "out.nhx"))
    assert code != 0
    assert "nhx" in err and "newick" in err
    assert "Traceback" not in err


def test_convert_falls_back_to_newick_for_an_unknown_extension(capsys, tree_file,
                                                               tmp_path):
    out_path = tmp_path / "out.unknownext"
    assert run(capsys, "convert", str(tree_file), str(out_path))[0] == 0
    assert out_path.read_text(encoding="utf-8").rstrip().endswith(";")


def test_render_writes_parsable_svg(capsys, tree_file, tmp_path):
    out_path = tmp_path / "tree.svg"
    code, _, _ = run(capsys, "render", str(tree_file), str(out_path))
    assert code == 0
    root = ET.fromstring(out_path.read_text(encoding="utf-8"))
    assert root.tag.endswith("svg")
    assert "Alpha" in out_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("mode", ["rectangular", "slanted", "circular",
                                  "radial", "unrooted"])
def test_render_supports_every_mode(capsys, tree_file, tmp_path, mode):
    out_path = tmp_path / f"{mode}.svg"
    code, _, _ = run(capsys, "render", str(tree_file), str(out_path),
                     "--mode", mode)
    assert code == 0
    ET.fromstring(out_path.read_text(encoding="utf-8"))


def test_render_honours_size_branch_mode_and_alignment(capsys, tree_file,
                                                       tmp_path):
    out_path = tmp_path / "sized.svg"
    code, _, _ = run(capsys, "render", str(tree_file), str(out_path),
                     "--width", "1200", "--height", "800",
                     "--branch-mode", "cladogram-aligned",
                     "--align-tips", "--ladderize", "asc")
    assert code == 0
    root = ET.fromstring(out_path.read_text(encoding="utf-8"))
    assert root.get("width").endswith("pt")
    assert float(root.get("width").removesuffix("pt")) >= 1200
    assert float(root.get("height").removesuffix("pt")) >= 800


def test_render_dark_theme_paints_a_dark_background(capsys, tree_file, tmp_path):
    from makeyourtree.style.theme import DARK

    out_path = tmp_path / "dark.svg"
    assert run(capsys, "render", str(tree_file), str(out_path),
               "--theme", "dark")[0] == 0
    root = ET.fromstring(out_path.read_text(encoding="utf-8"))
    background = root.find("{http://www.w3.org/2000/svg}rect")
    assert background.get("fill") == DARK.background.rgb_hex


def test_render_without_tip_labels_drops_the_names(capsys, tree_file, tmp_path):
    out_path = tmp_path / "bare.svg"
    assert run(capsys, "render", str(tree_file), str(out_path),
               "--no-tip-labels")[0] == 0
    assert "Alpha" not in out_path.read_text(encoding="utf-8")


def test_reroot_midpoint_writes_a_tree(capsys, tree_file, tmp_path):
    out_path = tmp_path / "rerooted.nwk"
    code, _, _ = run(capsys, "reroot", str(tree_file), str(out_path),
                     "--midpoint")
    assert code == 0
    assert out_path.read_text(encoding="utf-8").rstrip().endswith(";")
    code, out, _ = run(capsys, "info", str(out_path), "--json")
    assert json.loads(out)["leaves"] == 4


def test_reroot_midpoint_actually_moves_the_root(capsys, tree_file, tmp_path):
    """Guards the failure mode that "a tree came out" cannot see.

    Everything in :mod:`makeyourtree.ops` BUILDS a reversible command and returns
    it without touching the tree; the caller applies it.  A CLI that dropped
    the return value wrote its input straight back out and passed every check
    that only asked whether the output was a tree with four leaves.  The
    midpoint of the longest path is the property to assert instead.
    """
    from makeyourtree.core.traversal import iter_leaves
    from makeyourtree.io import load_tree

    out_path = tmp_path / "rerooted.nwk"
    assert run(capsys, "reroot", str(tree_file), str(out_path), "--midpoint")[0] == 0

    before = load_tree(str(tree_file))
    after = load_tree(str(out_path))
    assert after.to_newick() != before.to_newick(), "reroot was a no-op"

    depths = sorted(leaf.depth_len for leaf in after.leaves)
    assert depths[-1] == pytest.approx(depths[-2]), (
        "the two deepest tips must be equidistant from a midpoint root")
    assert sum(n.branch_length or 0.0 for n in after.nodes) == pytest.approx(
        sum(n.branch_length or 0.0 for n in before.nodes)), (
        "rerooting moves length between two edges; it never creates or destroys any")


def test_reroot_outgroup_writes_a_tree(capsys, tree_file, tmp_path):
    out_path = tmp_path / "outgrouped.nwk"
    code, _, _ = run(capsys, "reroot", str(tree_file), str(out_path),
                     "--outgroup", "Alpha,Beta")
    assert code == 0
    code, out, _ = run(capsys, "info", str(out_path), "--json")
    assert json.loads(out)["leaves"] == 4


def test_reroot_outgroup_puts_the_outgroup_on_its_own_side(capsys, tree_file,
                                                           tmp_path):
    from makeyourtree.core.traversal import iter_leaves
    from makeyourtree.io import load_tree

    out_path = tmp_path / "outgrouped.nwk"
    assert run(capsys, "reroot", str(tree_file), str(out_path),
               "--outgroup", "Alpha,Beta")[0] == 0
    after = load_tree(str(out_path))
    sides = [{leaf.name for leaf in iter_leaves(child)}
             for child in after.root.children]
    assert {"Alpha", "Beta"} in sides, (
        f"outgroup must be one whole child of the new root; got {sides}")


def test_render_ladderize_reorders_the_tips(capsys, tree_file, tmp_path):
    """``--ladderize`` must reach the layout, not just be accepted by argparse.

    Tip labels are emitted in row order, so the order they appear in the SVG is
    the order the layout put them in.  Ascending and descending must disagree.
    """
    order = {}
    for direction in ("asc", "desc"):
        out_path = tmp_path / f"{direction}.svg"
        assert run(capsys, "render", str(tree_file), str(out_path),
                   "--ladderize", direction)[0] == 0
        root = ET.fromstring(out_path.read_text(encoding="utf-8"))
        names = [e.text for e in root.iter(f"{SVG_NS}text")
                 if e.text in ("Alpha", "Beta", "Gamma", "Delta")]
        order[direction] = names
    assert len(order["asc"]) == 4
    assert order["asc"] == list(reversed(order["desc"])), (
        f"ladderize direction had no effect: {order}")


def test_reroot_with_an_unknown_outgroup_fails_cleanly(capsys, tree_file,
                                                       tmp_path):
    code, _, err = run(capsys, "reroot", str(tree_file),
                       str(tmp_path / "x.nwk"), "--outgroup", "Nosuchtaxon")
    assert code != 0
    assert "Nosuchtaxon" in err
    assert "Traceback" not in err


def test_reroot_requires_a_placement(capsys, tree_file, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(["reroot", str(tree_file), str(tmp_path / "x.nwk")])
    assert excinfo.value.code == 2


def test_no_subcommand_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_version_flag_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "makeyourtree" in capsys.readouterr().out


# ------------------------------------------------- output format, size, dpi
#
# The core cannot rasterise -- PNG and PDF arrive through an entry point that
# only exists with the desktop extra -- so these exercise what the Qt-free half
# owns: choosing the format, parsing physical lengths, and reporting the size.


def test_render_infers_svg_from_the_extension(capsys, tree_file, tmp_path):
    out_path = tmp_path / "figure.svg"
    code, _, _ = run(capsys, "render", str(tree_file), str(out_path))
    assert code == 0
    assert out_path.read_text(encoding="utf-8").lstrip().startswith("<svg")


def test_output_format_overrides_a_misleading_extension(capsys, tree_file,
                                                        tmp_path):
    out_path = tmp_path / "figure.dat"
    code, _, _ = run(capsys, "render", str(tree_file), str(out_path),
                     "--output-format", "svg")
    assert code == 0
    assert out_path.read_text(encoding="utf-8").lstrip().startswith("<svg")


@pytest.mark.parametrize("name", ["figure.bmp", "figure.jpg", "figure.pgn",
                                  "figure"])
def test_render_refuses_an_extension_it_cannot_map(capsys, tree_file, tmp_path,
                                                   name):
    """Guessing SVG produces a file whose name lies about its contents."""
    out_path = tmp_path / name
    code, _, err = run(capsys, "render", str(tree_file), str(out_path))
    assert code == 1
    assert "cannot tell the figure format" in err
    assert ".svg" in err and "--output-format" in err
    assert not out_path.exists()


@pytest.mark.parametrize("length", ["10in", "254mm", "25.4cm"])
def test_every_spelling_of_a_length_agrees(capsys, tree_file, tmp_path, length):
    """720pt, 10in, 254mm and 25.4cm are the same page, byte for byte.

    Comparing the spellings against each other rather than against a nominal
    number, because the produced page is not exactly the requested one: a
    requested size is a floor and the composition rounds outward from it. What
    must hold is that the unit conversion is exact, and identical output is the
    strongest way to say so.

    Tip labels are off because they are drawn beyond the body and push the page
    wider than asked -- deliberate, so a name is never clipped, but it would add
    a variable that has nothing to do with units.
    """
    reference = tmp_path / "reference.svg"
    candidate = tmp_path / f"{length}.svg"
    assert run(capsys, "render", str(tree_file), str(reference),
               "--width", "720pt", "--no-tip-labels")[0] == 0
    assert run(capsys, "render", str(tree_file), str(candidate),
               "--width", length, "--no-tip-labels")[0] == 0
    assert candidate.read_bytes() == reference.read_bytes()


def test_a_requested_width_is_honoured(capsys, tree_file, tmp_path):
    """A page far wider than the figure needs must actually be that wide."""
    out_path = tmp_path / "wide.svg"
    assert run(capsys, "render", str(tree_file), str(out_path),
               "--width", "10in", "--no-tip-labels")[0] == 0
    root = ET.fromstring(out_path.read_text(encoding="utf-8"))
    assert float(root.get("width").removesuffix("pt")) == pytest.approx(
        720.0, abs=5.0)


def test_a_bad_length_is_refused_without_a_traceback(capsys, tree_file,
                                                     tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(["render", str(tree_file), str(tmp_path / "x.svg"),
              "--width", "wide"])
    assert excinfo.value.code != 0
    assert "Traceback" not in capsys.readouterr().err


def test_a_bad_dpi_is_refused(capsys, tree_file, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(["render", str(tree_file), str(tmp_path / "x.png"), "--dpi", "0"])
    assert excinfo.value.code != 0


def test_page_preset_sets_the_page(capsys, tree_file, tmp_path):
    out_path = tmp_path / "a4.svg"
    code, _, _ = run(capsys, "render", str(tree_file), str(out_path), "--page",
                     "a4")
    assert code == 0
    root = ET.fromstring(out_path.read_text(encoding="utf-8"))
    assert float(root.get("width").removesuffix("pt")) >= 595.0


def test_landscape_swaps_the_page_axes(capsys, tree_file, tmp_path):
    portrait, landscape = tmp_path / "p.svg", tmp_path / "l.svg"
    run(capsys, "render", str(tree_file), str(portrait), "--page", "a4")
    run(capsys, "render", str(tree_file), str(landscape), "--page", "a4",
        "--landscape")
    p = ET.fromstring(portrait.read_text(encoding="utf-8"))
    l = ET.fromstring(landscape.read_text(encoding="utf-8"))
    assert (float(l.get("width").removesuffix("pt"))
            > float(p.get("width").removesuffix("pt")))


def test_an_explicit_width_beats_the_page_preset(capsys, tree_file, tmp_path):
    out_path = tmp_path / "wide.svg"
    code, _, _ = run(capsys, "render", str(tree_file), str(out_path),
                     "--page", "a4", "--width", "1000pt")
    assert code == 0
    root = ET.fromstring(out_path.read_text(encoding="utf-8"))
    assert float(root.get("width").removesuffix("pt")) >= 1000.0


def test_render_reports_the_produced_size(capsys, tree_file, tmp_path):
    """The size has to be discoverable without opening the file."""
    code, out, _ = run(capsys, "render", str(tree_file),
                       str(tmp_path / "f.svg"))
    assert code == 0
    assert "mm" in out and "vector" in out


def test_outgrowing_the_requested_page_is_said_out_loud(capsys, tree_file,
                                                       tmp_path):
    """A requested size is a floor, never a crop -- so it can be exceeded, and
    a user who is not told will find out in a submission system."""
    code, _, err = run(capsys, "render", str(tree_file),
                       str(tmp_path / "tiny.svg"), "--width", "20mm")
    assert code == 0
    assert "larger than the page you asked for" in err


def test_quiet_suppresses_the_size_report(capsys, tree_file, tmp_path):
    code, out, _ = run(capsys, "-q", "render", str(tree_file),
                       str(tmp_path / "f.svg"))
    assert code == 0
    assert out.strip() == ""


def test_an_unavailable_format_explains_itself(capsys, tree_file, tmp_path,
                                               monkeypatch):
    """With the core alone, `render figure.png` must instruct, not traceback."""
    from makeyourtree.render import exporters

    monkeypatch.setattr(exporters, "_cache", {"svg": exporters._export_svg})
    code, _, err = run(capsys, "render", str(tree_file),
                       str(tmp_path / "f.png"))
    assert code != 0
    assert "pip install" in err and "Traceback" not in err


def test_align_tips_says_it_was_ignored_in_unrooted_mode(capsys, tree_file,
                                                         tmp_path):
    """Silently accepting the flag leaves the user waiting for a change."""
    out_path = tmp_path / "figure.svg"
    code, _, err = run(capsys, "render", str(tree_file), str(out_path),
                       "--mode", "unrooted", "--align-tips")
    assert code == 0
    assert "render.align-tips-ignored" in err


def test_align_tips_is_silent_where_it_works(capsys, tree_file, tmp_path):
    out_path = tmp_path / "figure.svg"
    code, _, err = run(capsys, "render", str(tree_file), str(out_path),
                       "--mode", "rectangular", "--align-tips")
    assert code == 0
    assert "render.align-tips-ignored" not in err

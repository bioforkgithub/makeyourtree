# SPDX-License-Identifier: MIT
"""Command line interface.

The CLI is the headless half of MakeYourTree: inspecting, converting, rerooting and
rendering a tree without a display server.  Everything it does goes through the
same library entry points the desktop application uses, so a figure produced in
a batch job and one produced by clicking are the same figure.

Two conventions run through every subcommand.

*Diagnostics are data, not failures.*  Readers are lenient (see
:mod:`makeyourtree.core.diagnostics`); a file with a missing semicolon still opens
and the complaint goes to stderr, leaving stdout clean for the actual answer.

*A user-facing failure is a sentence, not a traceback.*  Anything deriving from
:class:`~makeyourtree.core.errors.MakeYourTreeError`, plus the usual filesystem errors,
is reported as one line on stderr with a non-zero exit code.  A traceback means
a bug in MakeYourTree, and only then should one appear.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence, TextIO

from . import __version__

__all__ = ["main", "build_parser"]

# Known figure formats, and the named page sizes --page accepts. Listed from
# the registry so a format added there appears here without another edit.
from .render.exporters import SUFFIXES as _OUTPUT_SUFFIXES
from .render.sizing import PAGE_SIZES as _PAGE_SIZES

_OUTPUT_FORMATS = tuple(sorted(set(_OUTPUT_SUFFIXES.values())))

EXIT_OK = 0
EXIT_ERROR = 1

_TREE_FORMATS = ("newick", "nhx", "nexus", "phyloxml")
_WRITE_FORMATS = ("newick", "nexus", "phyloxml")
_EXTENSIONS = {
    ".nwk": "newick", ".newick": "newick", ".tree": "newick", ".tre": "newick",
    ".nhx": "nhx", ".nex": "nexus", ".nexus": "nexus",
    ".xml": "phyloxml", ".phyloxml": "phyloxml",
}


# ------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="makeyourtree",
        description="Inspect, convert, reroot and render phylogenetic trees. "
                    "Independent project; not affiliated with, endorsed by, or "
                    "derived from any other phylogenetics package.")
    parser.add_argument("--version", action="version",
                        version=f"makeyourtree {__version__}")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="suppress parse diagnostics on stderr")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    def _reading_options(p: argparse.ArgumentParser) -> None:
        """Options that govern how the input file is interpreted.

        ``--internal-labels`` exists because the reader's own advice used to
        name a Python keyword argument, which a person at a terminal has no way
        to pass.  Every command that reads a tree offers it.
        """
        p.add_argument("--internal-labels", choices=("auto", "support", "name"),
                       default="auto", dest="internal_labels",
                       help="how to read a numeric label on an internal node: "
                            "'support' always as a support value, 'name' always "
                            "as a name, 'auto' (default) as support, saying so")

    info = sub.add_parser("info", help="summarise a tree file")
    info.add_argument("file")
    info.add_argument("--format", choices=_TREE_FORMATS,
                      help="override format detection")
    info.add_argument("--json", action="store_true", dest="as_json",
                      help="emit a JSON object instead of a text summary")
    _reading_options(info)
    info.set_defaults(func=_cmd_info)

    convert = sub.add_parser("convert", help="rewrite a tree in another format")
    convert.add_argument("input")
    convert.add_argument("output")
    convert.add_argument("--format", choices=_WRITE_FORMATS,
                         help="output format; inferred from the output "
                              "extension when omitted")
    convert.add_argument("--input-format", choices=_TREE_FORMATS,
                         help="override format detection on the input")
    _reading_options(convert)
    convert.set_defaults(func=_cmd_convert)

    render = sub.add_parser("render", help="lay a tree out and write a figure")
    render.add_argument("input")
    render.add_argument("output",
                        help="destination file; its extension chooses the "
                             "format unless --output-format overrides it")
    render.add_argument("--format", choices=_TREE_FORMATS,
                        help="override format detection on the input")
    render.add_argument("--output-format", choices=_OUTPUT_FORMATS, default=None,
                        help="figure format to write (default: from the output "
                             "extension). PNG and PDF need the desktop extra")
    render.add_argument("--dpi", type=_positive, default=300.0,
                        help="resolution for raster output, in pixels per inch "
                             "(default: 300, the usual journal minimum). "
                             "Ignored by the vector formats, which have no pixels")
    render.add_argument("--mode", default="rectangular",
                        choices=[m.value for m in _layout_modes()],
                        help="layout mode")
    render.add_argument("--branch-mode", default="phylogram",
                        choices=[m.value for m in _branch_modes()],
                        help="how the along-axis coordinate is derived")
    render.add_argument("--width", type=_length, default=None, metavar="LENGTH",
                        help="page width, with an optional unit: 180mm, 7in, "
                             "900pt, 1200px. A bare number is points (1/72 in). "
                             "The tree body gets what is left after the margins")
    render.add_argument("--height", type=_length, default=None, metavar="LENGTH",
                        help="page height, same units as --width")
    render.add_argument("--page", choices=sorted(_PAGE_SIZES), default=None,
                        help="named page size instead of --width/--height; "
                             "the column presets set a width and leave the "
                             "height to the figure")
    render.add_argument("--landscape", action="store_true",
                        help="swap the width and height of --page")
    render.add_argument("--row-spacing", type=float, default=None,
                        help="cross-axis distance between adjacent tip rows")
    render.add_argument("--ladderize", choices=("asc", "desc"), default=None,
                        help="order children by subtree size before laying out")
    render.add_argument("--align-tips", action="store_true",
                        help="flush tip labels and draw guide lines")
    render.add_argument("--no-tip-labels", action="store_true",
                        help="omit tip labels")
    render.add_argument("--track", action="append", default=[], metavar="FILE",
                        help="annotation table to attach; repeatable")
    render.add_argument("--theme", choices=("light", "dark"), default="light")
    _reading_options(render)
    render.set_defaults(func=_cmd_render)

    guide = sub.add_parser(
        "guide",
        help="answer a few questions and get a step-by-step plan")
    guide.add_argument("--tree", default="your-tree.nwk",
                       help="your tree file, woven into the commands the plan "
                            "hands you")
    guide.add_argument("--output", default=None, metavar="PLAN",
                       help="where to save the plan (default: figure.myplan)")
    guide.add_argument("--from-figure", default=None, metavar="FILE",
                       help="a published figure (PDF or image) to measure "
                            "first, pre-filling what it can establish")
    guide.add_argument("--name", default="figure",
                       help="stem for the figure the plan will produce")
    guide.add_argument("--yes", action="store_true",
                       help="accept every default without asking; useful for "
                            "a first look at what a plan contains")
    guide.set_defaults(func=_cmd_guide)

    plan = sub.add_parser(
        "plan", help="show, resume or export a saved plan")
    plan.add_argument("path", help="a .myplan file")
    plan.add_argument("--done", metavar="STEP", default=None,
                      help="mark a step finished, by number or id")
    plan.add_argument("--undo", metavar="STEP", default=None,
                      help="mark a step unfinished again")
    plan.add_argument("--note", default=None,
                      help="attach a note to the step named by --done/--undo")
    plan.add_argument("--export", metavar="FILE", default=None,
                      help="write the plan as a Markdown checklist")
    plan.add_argument("--all", action="store_true",
                      help="list every step, not just what is left")
    plan.set_defaults(func=_cmd_plan)

    reroot = sub.add_parser("reroot", help="place a new root on a tree")
    reroot.add_argument("input")
    reroot.add_argument("output")
    reroot.add_argument("--format", choices=_TREE_FORMATS,
                        help="override format detection on the input")
    reroot.add_argument("--output-format", choices=_WRITE_FORMATS,
                        help="output format; inferred from the extension")
    where = reroot.add_mutually_exclusive_group(required=True)
    where.add_argument("--midpoint", action="store_true",
                       help="root at the midpoint of the longest tip-to-tip path")
    where.add_argument("--outgroup", metavar="TAXA",
                       help="comma-separated taxon names to root against")
    _reading_options(reroot)
    reroot.set_defaults(func=_cmd_reroot)

    return parser


def _length(text: str) -> float:
    """argparse type for a physical length, in points."""
    from .render.sizing import LengthError, parse_length
    try:
        return parse_length(text)
    except LengthError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _positive(text: str) -> float:
    """argparse type for a strictly positive number."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not (value > 0) or value != value or value in (float("inf"),):
        raise argparse.ArgumentTypeError(f"must be greater than zero, got {text!r}")
    return value


def _layout_modes():
    from .layout.params import LayoutMode
    return list(LayoutMode)


def _branch_modes():
    from .layout.params import BranchMode
    return list(BranchMode)


# ------------------------------------------------------------------ helpers


def _format_for(path: str, explicit: str | None, default: str = "newick") -> str:
    if explicit:
        return explicit
    import os
    ext = os.path.splitext(path)[1].lower()
    return _EXTENSIONS.get(ext, default)


def _report(sink, stream: TextIO, quiet: bool) -> None:
    if quiet or not sink:
        return
    for diagnostic in sink:
        stream.write(diagnostic.format() + "\n")
    if sink.suppressed:
        stream.write(f"... and {sink.suppressed} further diagnostics "
                     f"(suppressed)\n")


def _load(path: str, fmt: str | None, sink, args=None):
    """Read *path*, honouring the reading options the command was given.

    Every reader absorbs keywords it does not use, so the option can be passed
    unconditionally rather than switched on the detected format.
    """
    from .io import load_tree

    kw = {}
    internal = getattr(args, "internal_labels", None)
    if internal:
        kw["internal_labels"] = internal
    return load_tree(path, format=fmt, sink=sink, **kw)


def _write_tree(tree, path: str, fmt: str) -> None:
    from .io import save_tree
    save_tree(tree, path, format=fmt)


# ----------------------------------------------------------------- commands


def _cmd_info(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    from .core.diagnostics import DiagnosticSink
    from .io.detect import detect_format, read_source

    sink = DiagnosticSink()
    text, _origin = read_source(args.file)
    detected = args.format or detect_format(text).format
    tree = _load(args.file, args.format, sink, args)
    tree.refresh()

    payload: dict[str, Any] = {
        "path": args.file,
        "format": detected,
        "name": tree.name,
        "rooted": bool(tree.rooted),
        "leaves": tree.n_leaves,
        "nodes": tree.n_nodes,
        "height": tree.root.height,
        "max_root_to_tip": tree.max_root_to_tip,
        "binary": tree.is_binary(),
        "has_branch_lengths": tree.has_branch_lengths,
        "has_support": tree.has_support,
        "ultrametric": tree.is_ultrametric(),
        "negative_lengths": sum(
            1 for n in tree.nodes
            if n.parent is not None and (n.branch_length or 0.0) < 0.0),
        "diagnostics": [
            {"severity": str(d.severity), "code": d.code, "message": d.message,
             "line": d.line, "col": d.col}
            for d in sink
        ],
    }
    # Diagnostics go to stderr in both shapes, so `--json` can be piped.
    _report(sink, err, args.quiet)
    if args.as_json:
        out.write(json.dumps(payload, indent=2, default=str) + "\n")
        return EXIT_OK

    out.write(f"path            {payload['path']}\n")
    out.write(f"format          {payload['format']}\n")
    if tree.name:
        out.write(f"name            {tree.name}\n")
    out.write(f"leaves          {payload['leaves']}\n")
    out.write(f"nodes           {payload['nodes']}\n")
    out.write(f"rooted          {'yes' if payload['rooted'] else 'no'}\n")
    out.write(f"binary          {'yes' if payload['binary'] else 'no'}\n")
    out.write(f"height (edges)  {payload['height']}\n")
    out.write(f"max root-to-tip {payload['max_root_to_tip']:g}\n")
    out.write(f"branch lengths  {'yes' if payload['has_branch_lengths'] else 'no'}\n")
    out.write(f"support values  {'yes' if payload['has_support'] else 'no'}\n")
    out.write(f"ultrametric     {'yes' if payload['ultrametric'] else 'no'}\n")
    # Printed only when there are any: a "negative lengths 0" line on every
    # ordinary tree would train the reader to skip the block that matters.
    if payload["negative_lengths"]:
        out.write(f"negative lengths {payload['negative_lengths']}\n")
    return EXIT_OK


def _cmd_convert(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    from .core.diagnostics import DiagnosticSink

    sink = DiagnosticSink()
    tree = _load(args.input, args.input_format, sink, args)
    fmt = _format_for(args.output, args.format)
    if fmt not in _WRITE_FORMATS:
        raise _UserError(f"cannot write format {fmt!r}; "
                         f"choose one of {', '.join(_WRITE_FORMATS)}")
    _write_tree(tree, args.output, fmt)
    _report(sink, err, args.quiet)
    return EXIT_OK


def _cmd_reroot(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    from .core.diagnostics import DiagnosticSink
    from .ops import midpoint_root, outgroup_root

    sink = DiagnosticSink()
    tree = _load(args.input, args.format, sink, args)
    if args.midpoint:
        command = midpoint_root(tree)
    else:
        taxa = [t.strip() for t in args.outgroup.split(",") if t.strip()]
        if not taxa:
            raise _UserError("--outgroup needs at least one taxon name")
        missing = [t for t in taxa if tree.by_name(t) is None]
        if missing:
            raise _UserError("outgroup taxa not found in tree: "
                             + ", ".join(missing))
        command = outgroup_root(tree, taxa)
    # Every entry point in makeyourtree.ops BUILDS a reversible command and returns
    # it; nothing is mutated until it is applied.  A CLI has no history to push
    # onto, so it applies the command directly -- but it must apply it, or the
    # subcommand silently writes the input back out unchanged.
    command.apply(tree)
    tree.refresh()
    fmt = _format_for(args.output, args.output_format)
    _write_tree(tree, args.output, fmt)
    _report(sink, err, args.quiet)
    return EXIT_OK


def _cmd_render(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    from .core.diagnostics import DiagnosticSink
    from .doc.document import Document
    from .layout.params import BranchMode, LayoutMode, LayoutParams
    from .render.exporters import ExportError, export_scene, format_for_path
    from .scene.compose import compose
    from .style.theme import DARK, LIGHT

    # An unrecognised extension is a mistake, not a licence to guess: writing
    # SVG bytes into "figure.bmp" produces a file every downstream tool refuses,
    # and says nothing about why.  format_for_path keeps its permissive default
    # for callers that have already decided; here the user has not.
    fmt = args.output_format
    if not fmt:
        fmt = format_for_path(args.output, default="")
        if not fmt:
            known = ", ".join(sorted(_OUTPUT_SUFFIXES))
            raise _UserError(
                f"cannot tell the figure format from {args.output!r}; name the "
                f"file with one of {known}, or pass --output-format")
    width, height = _page_dimensions(args)

    sink = DiagnosticSink()
    tree = _load(args.input, args.format, sink, args)
    if args.ladderize:
        from .ops import ladderize
        ladderize(tree, ascending=args.ladderize == "asc").apply(tree)
    tree.refresh()

    params = LayoutParams(mode=LayoutMode(args.mode),
                          branch_mode=BranchMode(args.branch_mode),
                          align_tips=bool(args.align_tips),
                          show_tip_labels=not args.no_tip_labels)
    if params.align_tips and params.mode is LayoutMode.UNROOTED:
        # Tips radiate in every direction here, so there is no edge to flush
        # them against.  Accepting the flag in silence leaves the user waiting
        # for a change that was never going to happen.
        sink.info("render.align-tips-ignored",
                  "--align-tips has no meaning in an unrooted drawing, where "
                  "tips point in every direction; it was ignored")
        params.align_tips = False
    # --width / --height name the page; the layout gets the page minus margins,
    # and the page is then a floor so a long label can still push it wider.
    if width is not None:
        params.width = max(50.0, width - 2.0 * params.margin)
    if height is not None:
        params.height = max(50.0, height - 2.0 * params.margin)
    if args.row_spacing is not None:
        params.row_spacing = args.row_spacing

    theme = DARK if args.theme == "dark" else LIGHT
    document = Document(tree=tree, params=params, theme=theme)
    for path in args.track:
        document.add_track(_load_track(path, tree, sink))

    size = None
    if width is not None or height is not None:
        size = (width or 0.0, height or 0.0)
    scene = compose(document, size=size, sink=sink)

    try:
        export_scene(scene, args.output, fmt, dpi=args.dpi,
                     title=tree.name or args.input)
    except ExportError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_ERROR
    _report(sink, err, args.quiet)
    _report_size(scene, fmt, args.dpi, width, height, args.output,
                 out, err, args.quiet)
    return EXIT_OK


def _report_size(scene, fmt: str, dpi: float,
                 want_w: float | None, want_h: float | None,
                 path: str, out: TextIO, err: TextIO, quiet: bool) -> None:
    """Say how big the figure actually is, in the units the format is measured in.

    Printed because the alternative is a user discovering the size in a journal
    submission system. It also gives the only honest place to mention that a
    requested page was outgrown: ``compose`` treats a requested size as a floor
    and never crops, so asking for a page narrower than the labels need is
    silently ignored, and silence there is how a figure ends up the wrong width.
    """
    from .render.exporters import is_raster
    from .render.sizing import format_length, pixels_for

    if quiet:
        return
    width, height = float(scene.width), float(scene.height)
    physical = (f"{format_length(width, 'mm')} x {format_length(height, 'mm')}")
    if is_raster(fmt):
        size = (f"{pixels_for(width, dpi)} x {pixels_for(height, dpi)} px "
                f"at {dpi:g} dpi ({physical})")
    else:
        size = f"{physical} (vector)"
    print(f"{path}  {size}", file=out)

    outgrown = []
    if want_w is not None and width > want_w + 0.5:
        outgrown.append(f"width {format_length(width, 'mm')} > "
                        f"{format_length(want_w, 'mm')}")
    if want_h is not None and height > want_h + 0.5:
        outgrown.append(f"height {format_length(height, 'mm')} > "
                        f"{format_length(want_h, 'mm')}")
    if outgrown:
        print("note: the figure is larger than the page you asked for "
              f"({'; '.join(outgrown)}). The requested size is a floor, never a "
              "crop, so nothing was cut off. To fit it, shorten the tip labels "
              "with --no-tip-labels, reduce --row-spacing, or scale the figure "
              "down when you place it.", file=err)


def _cmd_guide(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    """Walk the interview, then write a plan.

    Interactive by default and non-interactive with ``--yes``, because the first
    thing many people want is to see what a plan even looks like before
    committing to answering anything.
    """
    from .guide.figure import FigureError, inspect_figure
    from .guide.plan import PLAN_EXTENSION, save_plan
    from .guide.session import GuideSession

    session = GuideSession(tree_file=args.tree, output_stem=args.name)

    if args.from_figure:
        try:
            reading = inspect_figure(args.from_figure)
        except FigureError as exc:
            print(f"error: {exc}", file=err)
            return EXIT_ERROR
        taken = session.adopt(reading)
        print("What I could measure in that figure:", file=out)
        for line in reading.lines():
            print(f"  {line}", file=out)
        if taken:
            print(f"\nPre-filled: {', '.join(taken)}. "
                  f"You can change any of it below.\n", file=out)
        else:
            print("\nNothing conclusive, so every question is still open.\n",
                  file=out)

    if not args.yes:
        code = _run_interview(session, out, err)
        if code != EXIT_OK:
            return code

    plan = session.to_plan()
    target = args.output or f"{args.name}{PLAN_EXTENSION}"
    save_plan(plan, target)

    print(f"\n{plan.title}", file=out)
    print(f"{len(plan)} steps, saved to {target}\n", file=out)
    _print_steps(plan, out, only_open=False)
    print(f"Resume any time with:  makeyourtree plan {target}", file=out)
    return EXIT_OK


def _run_interview(session, out: TextIO, err: TextIO) -> int:
    """Ask the open questions on the terminal.

    Enter accepts the default (skip). A bad answer re-asks rather than aborting:
    losing a half-finished interview to a typo would be a poor trade.
    """
    print("Answer what you can. Press Enter to skip a question, or type 'q' "
          "to stop and keep what you have.\n", file=out)
    while True:
        question = session.next()
        if question is None:
            return EXIT_OK
        answered, total = session.progress()
        print(f"[{answered + 1}/{total}] {question.text}", file=out)
        if question.help:
            print(f"      {question.help}", file=out)
        for index, choice in enumerate(question.choices, start=1):
            suffix = f"  -- {choice.detail}" if choice.detail else ""
            print(f"  {index}. {choice.label}{suffix}", file=out)
        if question.multi:
            print("  (several allowed, separated by commas)", file=out)

        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nStopping there; what you have answered is kept.", file=out)
            return EXIT_OK

        if raw.lower() in {"q", "quit", "exit"}:
            print("Stopping there; what you have answered is kept.", file=out)
            return EXIT_OK
        if not raw:
            session.skip(question.id)
            print("", file=out)
            continue

        picked = _resolve_choices(question, raw)
        if picked is None:
            print("  I did not recognise that. Type the number of a choice.\n",
                  file=err)
            continue
        try:
            session.answer(question.id, picked)
        except ValueError as exc:
            print(f"  {exc}\n", file=err)
            continue
        print("", file=out)


def _resolve_choices(question, raw: str):
    """Turn what was typed into a legal answer, or None if it makes no sense."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    values: list[str] = []
    for part in parts:
        if part.isdigit():
            index = int(part) - 1
            if not (0 <= index < len(question.choices)):
                return None
            values.append(question.choices[index].value)
        elif any(c.value == part for c in question.choices):
            values.append(part)
        else:
            return None
    if not values:
        return None
    return values if question.multi else values[0]


def _print_steps(plan, out: TextIO, only_open: bool = True) -> None:
    for index, step in enumerate(plan.steps, start=1):
        if only_open and step.done:
            continue
        box = "x" if step.done else " "
        tail = "  (optional)" if step.optional else ""
        print(f"  {index:>2}. [{box}] {step.title}{tail}", file=out)
        if step.detail:
            for line in step.detail.splitlines():
                if line.strip():
                    print(f"        {line.strip()}", file=out)
        if step.command:
            print(f"        $ {step.command}", file=out)
        if step.note:
            print(f"        note: {step.note}", file=out)
        print("", file=out)


def _cmd_plan(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    """Show a plan, tick a step off, or export it."""
    from .guide.plan import PlanError, load_plan, save_plan

    try:
        plan = load_plan(args.path)
    except PlanError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_ERROR

    changed = False
    for target, done in ((args.done, True), (args.undo, False)):
        if target is None:
            continue
        step_id = _find_step(plan, target)
        if step_id is None:
            print(f"error: no step {target!r} in this plan", file=err)
            return EXIT_ERROR
        plan.mark(step_id, done, note=args.note)
        changed = True

    if changed:
        save_plan(plan, args.path)

    if args.export:
        with open(args.export, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(plan.to_markdown())
        print(f"wrote {args.export}", file=out)
        return EXIT_OK

    print(f"{plan.title}", file=out)
    print(f"{plan.progress()}. Last updated {plan.updated}.\n", file=out)

    upcoming = plan.next_step()
    if upcoming is None:
        print("Every step is done.", file=out)
        return EXIT_OK

    if args.all:
        _print_steps(plan, out, only_open=False)
    else:
        print("Next:", file=out)
        _print_steps(plan, out, only_open=True)
        print(f"Mark it done with:  makeyourtree plan {args.path} "
              f"--done {upcoming.id}", file=out)
    return EXIT_OK


def _find_step(plan, target: str) -> str | None:
    """Accept either a step id or its 1-based position."""
    if target.isdigit():
        index = int(target) - 1
        if 0 <= index < len(plan.steps):
            return plan.steps[index].id
        return None
    return next((s.id for s in plan.steps if s.id == target), None)


def _page_dimensions(args: argparse.Namespace) -> tuple[float | None, float | None]:
    """Resolve --page, --landscape, --width and --height into points.

    An explicit --width or --height wins over --page, so a preset can be used
    as a starting point and one axis overridden. A preset height of zero means
    "as tall as the figure needs", which is what the journal column widths
    want, so it becomes ``None`` rather than a zero-height page.
    """
    from .render.sizing import page_size

    width, height = args.width, args.height
    if getattr(args, "page", None):
        page_w, page_h = page_size(args.page)
        if getattr(args, "landscape", False):
            page_w, page_h = page_h, page_w
        if width is None:
            width = page_w or None
        if height is None:
            height = page_h or None
    return width, height


def _load_track(path: str, tree, sink):
    """Read one annotation file and bind it to *tree*.

    The loader is called through its signature rather than positionally: it is
    the one library entry point whose optional arguments the CLI does not
    control, and a keyword mismatch here would be a confusing failure for a
    user who only mistyped a filename.
    """
    import inspect

    from .annot import load_annotation
    from .core.errors import TrackDataError

    kwargs = {}
    accepted = inspect.signature(load_annotation).parameters
    if "sink" in accepted:
        kwargs["sink"] = sink
    if "tree" in accepted:
        kwargs["tree"] = tree
        result = load_annotation(path, **kwargs)
    else:
        result = load_annotation(path, tree, **kwargs)
    if isinstance(result, (list, tuple)):
        if not result:
            raise TrackDataError(f"{path}: no track defined in annotation file")
        return result[0]
    return result


# -------------------------------------------------------------------- entry


class _UserError(Exception):
    """A mistake in the invocation, reported as a sentence rather than a trace."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    out, err = sys.stdout, sys.stderr
    try:
        return int(args.func(args, out, err))
    except _UserError as exc:
        err.write(f"makeyourtree: {exc}\n")
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        err.write("makeyourtree: interrupted\n")
        return 130
    except FileNotFoundError as exc:
        err.write(f"makeyourtree: no such file: {exc.filename}\n")
        return EXIT_ERROR
    except (IsADirectoryError, PermissionError, OSError) as exc:
        err.write(f"makeyourtree: {exc.strerror or exc}: {exc.filename or ''}\n".rstrip()
                  + "\n")
        return EXIT_ERROR
    except Exception as exc:
        from .core.errors import MakeYourTreeError
        if isinstance(exc, (MakeYourTreeError, ValueError, KeyError)):
            err.write(f"makeyourtree: {exc}\n")
            return EXIT_ERROR
        raise


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())

# SPDX-License-Identifier: MIT
"""Tree file reading and writing.

All formats here are open published specifications.  Reading is deliberately
lenient: real files violate the specs constantly, and refusing to open one is
almost never what the user wants.  Problems are recorded in a
:class:`~makeyourtree.core.diagnostics.DiagnosticSink` and reading continues.
"""
from .detect import FormatInfo, detect_format
from .newick import read_newick, read_newick_multi, write_newick
from .nexus import read_nexus, write_nexus
from .phyloxml import read_phyloxml, write_phyloxml
from .writer import FORMATS, save_tree, save_trees, write_tree

__all__ = ["load_tree", "load_trees", "save_tree", "save_trees", "write_tree",
           "FORMATS", "detect_format", "FormatInfo",
           "read_newick", "read_newick_multi", "write_newick", "read_nexus",
           "write_nexus", "read_phyloxml", "write_phyloxml"]


def load_tree(source, *, format=None, sink=None, **kw):
    """Read a single tree from a path, file object, string or bytes.

    *format* is one of ``newick``, ``nexus``, ``phyloxml``, ``nhx``; when
    omitted it is sniffed from the content by :func:`detect_format`.  A file
    holding several trees yields the first, with a diagnostic noting the rest;
    use :func:`load_trees` to get them all.
    """
    trees = load_trees(source, format=format, sink=sink, **kw)
    if not trees:
        from ..core.errors import ParseError
        raise ParseError("no tree found in input")
    if len(trees) > 1 and sink is not None:
        sink.info("io.multiple-trees",
                  f"file contains {len(trees)} trees; loaded the first")
    return trees[0]


def load_trees(source, *, format=None, sink=None, **kw):
    """Read every tree in *source*, returning a list."""
    from ..core.diagnostics import DiagnosticSink
    from ..core.errors import FormatError
    from .detect import detect_format, read_source

    sink = sink if sink is not None else DiagnosticSink()
    text, origin = read_source(source)
    fmt = format or detect_format(text).format
    if fmt in ("newick", "nhx"):
        trees = read_newick_multi(text, sink=sink, **kw)
    elif fmt == "nexus":
        trees = read_nexus(text, sink=sink, **kw)
    elif fmt == "phyloxml":
        trees = read_phyloxml(text, sink=sink, **kw)
    else:
        raise FormatError(f"unsupported tree format {fmt!r}")
    for t in trees:
        t.metadata.setdefault("source_format", fmt)
        if origin:
            t.metadata.setdefault("source_path", origin)
        _post_read_checks(t, sink)
    return trees


def _post_read_checks(tree, sink) -> None:
    """Report the two hazards no individual reader is placed to see.

    Both are properties of the finished tree rather than of any one token, and
    both matter in every format, so checking them once here beats four
    near-identical checks that would drift apart.  Neither is an error: the
    file is readable and the tree is usable, but a user who is not told will
    draw a conclusion the data does not support.
    """
    if sink is None:
        return
    _report_duplicate_tip_names(tree, sink)
    _report_negative_lengths(tree, sink)


def _report_duplicate_tip_names(tree, sink) -> None:
    """Two tips with one name silently break annotation matching.

    Tracks bind records to nodes by name.  With the name repeated, a row lands
    on whichever tip matched first and the reader sees a value on a tip that
    was never measured -- the kind of error that survives review because the
    figure looks perfectly ordinary.
    """
    from collections import Counter

    counts = Counter(n.name for n in tree.nodes if n.is_tip and n.name)
    repeated = [(name, k) for name, k in counts.items() if k > 1]
    if not repeated:
        return
    repeated.sort(key=lambda pair: (-pair[1], pair[0]))
    shown = ", ".join(f"{name!r} (x{k})" for name, k in repeated[:5])
    if len(repeated) > 5:
        shown += f", and {len(repeated) - 5} more"
    sink.warn("io.duplicate-tip-name",
              f"{len(repeated)} tip name(s) appear more than once: {shown}. "
              f"Annotation rows are matched by name, so a row for a repeated "
              f"name cannot be aimed at one tip in particular")


def _report_negative_lengths(tree, sink) -> None:
    """Negative lengths are legitimate data that the drawing cannot show.

    Neighbour-joining, BioNJ and least-squares fitting all produce them.  The
    reader keeps them exactly as written -- clamping belongs to the drawing,
    not to the data -- but the user should learn of them here, when the file is
    opened, rather than wondering later why a branch has no length on screen.
    """
    count = sum(1 for n in tree.nodes
                if n.parent is not None and (n.branch_length or 0.0) < 0.0)
    if count:
        sink.info("io.negative-branch-lengths",
                  f"{count} negative branch length(s); they are kept in the "
                  f"data and drawn as zero-length edges unless the layout is "
                  f"told otherwise")

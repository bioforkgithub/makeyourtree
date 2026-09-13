# SPDX-License-Identifier: MIT
"""Turning annotation tables into bound tracks.

This is the seam between the file formats and :mod:`makeyourtree.tracks`: a table
is inert text keyed by node *name*, a track holds values keyed by node *id*.
Binding happens exactly once here, which is what lets every downstream consumer
(layout, drawing, hit-testing, export) work with integer ids.

Matching is by name, and the ``match`` setting decides whether internal node
names are eligible.  Keys that hit nothing are never dropped silently: they go
to ``TrackData.unmatched`` and to the diagnostic sink, because a file that
matches 10 % of the tree is a user error worth showing, not an empty track.
"""

from __future__ import annotations

import csv
import io
import os
from typing import Any

from ..core.diagnostics import DiagnosticSink
from ..core.errors import FormatError
from ..core.tree import Tree
from ..tracks.base import Track, get_track_class
from .parser import _coerce_cell, parse_annotation
from .table import AnnotationTable

__all__ = ["track_from_table", "load_annotation", "track_from_delimited"]

_SNIFF_DELIMITERS = ",\t;|"
_MAX_INLINE_PATH = 4096
"""Longest string still worth testing as a filesystem path.  Anything longer is
certainly document text, and on Windows a long string sent to ``os.path.exists``
raises rather than returning False."""


def track_from_table(table: AnnotationTable, tree: Tree, *,
                     sink: DiagnosticSink | None = None) -> Track:
    """Construct the track *table* describes and bind its records to *tree*.

    The table's colour map and legend settings are handed to the track as the
    ``colors`` and ``legend`` options; a track type that understands them picks
    them up from there, and one that does not simply ignores them.
    """
    try:
        klass = get_track_class(table.track_type)
    except KeyError as exc:
        raise FormatError(str(exc.args[0])) from None

    options: dict[str, Any] = dict(table.options)
    if table.colors:
        options.setdefault("colors", dict(table.colors))
    if table.legend:
        options.setdefault("legend", dict(table.legend))
    _report_unknown_options(klass, options, table, sink)

    track = klass(id=table.track_id, title=table.title, options=options)
    track.data.source = table.source
    match_internal = table.match == "all"
    _report_ambiguous_keys(table, tree, match_internal, sink)
    track.bind(tree, table.records, columns=table.columns,
               match_internal=match_internal, sink=sink)
    if sink is not None and not track.data.rows and table.records:
        sink.error("annot.no-match",
                   f"{table.track_type} '{table.title}': none of "
                   f"{len(table.records)} key(s) matched a node name")
    return track


def _report_ambiguous_keys(table: AnnotationTable, tree: Tree,
                           match_internal: bool,
                           sink: DiagnosticSink | None) -> None:
    """Say when one record could be aimed at several nodes.

    :meth:`Track.bind` gives the value to *every* node sharing the name, which
    is the only defensible choice -- picking one would put a measurement on an
    arbitrary tip -- but it means a single row can paint several cells.  The
    tree reader already warns that the names repeat (``io.duplicate-tip-name``);
    this says which annotation rows are actually affected, which is the part
    that changes what the figure claims.
    """
    if sink is None or not table.records:
        return
    from collections import Counter

    counts = Counter(n.name for n in tree.nodes
                     if n.name and (match_internal or not n.children))
    ambiguous = [(key, counts[key]) for key in table.records if counts[key] > 1]
    if not ambiguous:
        return
    ambiguous.sort(key=lambda pair: (-pair[1], pair[0]))
    shown = ", ".join(f"{key!r} (x{k})" for key, k in ambiguous[:5])
    more = f", and {len(ambiguous) - 5} more" if len(ambiguous) > 5 else ""
    sink.warn("annot.ambiguous-key",
              f"{table.track_type} '{table.title}': {len(ambiguous)} key(s) "
              f"match more than one node and are drawn on every match: "
              f"{shown}{more}")


def _report_unknown_options(klass: type[Track], options: dict[str, Any],
                            table: AnnotationTable,
                            sink: DiagnosticSink | None) -> None:
    """Warn about option keys the track type does not declare, but keep them.

    A key we do not recognise is far more likely to come from a newer build
    than to be meaningless, so it stays in ``Track.options`` and is written back
    out on save.
    """
    if sink is None:
        return
    known = set(klass.default_options()) | {"colors", "legend"}
    for key in options:
        if key not in known:
            sink.warn("annot.unknown-option",
                      f"{klass.type_id} does not declare option {key!r}; kept")


def load_annotation(path_or_text: str | os.PathLike[str], tree: Tree, *,
                    sink: DiagnosticSink | None = None) -> Track:
    """Read a ``.mytrack`` file (or a string holding one) and bind it to *tree*."""
    text, origin = _read_source(path_or_text)
    table = parse_annotation(text, sink=sink, source=origin)
    return track_from_table(table, tree, sink=sink)


def track_from_delimited(text: str | os.PathLike[str], tree: Tree, *,
                         type_id: str, sink: DiagnosticSink | None = None,
                         **opts: Any) -> Track:
    """Build a track from a plain CSV/TSV table whose first row is a header.

    The common case is a user with a spreadsheet and no ``.mytrack`` file at all.
    The first column holds the node key and every other column becomes a track
    column.  ``title``, ``id`` and ``match`` are taken from *opts* if present;
    everything else in *opts* becomes a track option.
    """
    content, origin = _read_source(text)
    table = AnnotationTable(track_type=type_id, source=origin)
    table.title = str(opts.pop("title", "") or "")
    table.track_id = str(opts.pop("id", "") or "")
    match = str(opts.pop("match", "leaves")).lower()
    table.match = match if match in ("leaves", "all") else "leaves"
    table.options = dict(opts)

    rows = list(csv.reader(io.StringIO(content), _dialect(content, sink)))
    rows = [r for r in rows if any(f.strip() for f in r)]
    if not rows:
        if sink is not None:
            sink.warn("annot.no-data", "delimited file holds no rows")
        return track_from_table(table, tree, sink=sink)

    header = rows[0]
    table.columns = [_column_name(name, i) for i, name in enumerate(header[1:])]
    ncols = len(table.columns)
    for lineno, row in enumerate(rows[1:], start=2):
        key = row[0].strip()
        if not key:
            if sink is not None:
                sink.warn("annot.empty-key", "record has no node key; skipped",
                          line=lineno)
            continue
        values: list[Any] = [_coerce_cell(f, False) for f in row[1:ncols + 1]]
        values.extend([None] * (ncols - len(values)))
        if key in table.records and sink is not None:
            sink.warn("annot.duplicate-key",
                      f"duplicate record for {key!r}; the later one wins", line=lineno)
        table.records[key] = values
    return track_from_table(table, tree, sink=sink)


def _column_name(name: str, index: int) -> str:
    name = name.strip()
    if name:
        return name
    return "value" if index == 0 else f"value{index + 1}"


def _dialect(content: str, sink: DiagnosticSink | None) -> Any:
    """Sniff the delimiter, falling back to the tab/comma rule of the ``.mytrack`` grammar.

    ``csv.Sniffer`` is a heuristic over quoting and column consistency and it
    does give up on short or ragged files, so the fallback matters more often
    than one would like.
    """
    sample = content[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=_SNIFF_DELIMITERS)
    except csv.Error:
        pass
    first = sample.splitlines()[0] if sample.splitlines() else ""
    delim = "\t" if "\t" in first else ","
    if sink is not None:
        sink.info("annot.sniff-failed",
                  f"could not sniff the delimiter; assuming {delim!r}")

    class _Fallback(csv.Dialect):
        delimiter = delim
        quotechar = '"'
        doublequote = True
        skipinitialspace = True
        lineterminator = "\n"
        quoting = csv.QUOTE_MINIMAL

    return _Fallback()


def _read_source(source: str | os.PathLike[str]) -> tuple[str, str | None]:
    """Accept a path or the document text itself, returning (text, origin)."""
    if isinstance(source, os.PathLike):
        path = os.fspath(source)
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            return fh.read(), path
    if "\n" not in source and len(source) < _MAX_INLINE_PATH:
        try:
            is_file = os.path.isfile(source)
        except (OSError, ValueError):   # embedded NULs, illegal characters
            is_file = False
        if is_file:
            with open(source, "r", encoding="utf-8-sig", newline="") as fh:
                return fh.read(), source
    return source, None

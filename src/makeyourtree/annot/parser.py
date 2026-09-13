# SPDX-License-Identifier: MIT
"""Reader and writer for the MakeYourTree annotation table (``.mytrack``).

The grammar is specified in :mod:`makeyourtree.annot.table`; that docstring is
normative and this module is its executable form.  Three properties drive the
implementation:

*Leniency.*  A user hand-edits these files, so anything that can be understood
is understood: unknown sections and unknown keys are recorded as a
:class:`~makeyourtree.core.diagnostics.Diagnostic` and kept rather than dropped,
because silently discarding a line a newer build wrote is worse than carrying
it.  Only a table that declares no track type is genuinely unusable, and that
alone raises.

*Round-tripping.*  ``parse_annotation(write_annotation(t)) == t`` holds for
every table this module can produce.  That is why the writer quotes any field
whose bare form would be re-read as something else (a number, ``-``, a
boolean), and why unknown material is folded into ``options`` where the writer
can find it again.

*Missing is not zero.*  An empty field or ``-`` becomes ``None``.  Tracks draw
a gap there; a zero would be a fabricated measurement.

Field quoting follows the CSV convention of RFC 4180 s2: a field may be wrapped
in ``"``, and a literal quote inside such a field is written twice.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ..core.diagnostics import DiagnosticSink
from ..core.errors import ParseError
from ..style.color import Color, parse_color
from .table import MAGIC, AnnotationTable

__all__ = ["parse_annotation", "write_annotation"]

_SECTION_RE = re.compile(r"^\[\s*([^\]]*?)\s*\]$")
_SEPARATORS: dict[str, re.Pattern[str]] = {
    "\t": re.compile(r"\t"),
    ",": re.compile(r","),
    " ": re.compile(r" {2,}"),
}
"""The three separators, in detection order.  ``" "`` means "a run of two or
more spaces", which is what a column-aligned file pasted out of a terminal
looks like."""

_KNOWN_SECTIONS = frozenset({"track", "options", "columns", "colors", "legend", "data"})
_LEGEND_KEYS = frozenset({"title", "show", "order"})
_MATCH_VALUES = frozenset({"leaves", "all"})

_HEADER_KEYS = frozenset({"id", "key", "name", "node", "label", "taxon", "tip", "leaf"})
"""First-column words that mark the opening data line as a header rather than a
record.  Guessing more aggressively than this risks eating a real record, and a
lost record is a worse failure than a generically named column."""

_NO_VALUE = "-"
_TRUE = frozenset({"true", "yes", "on", "1"})
_FALSE = frozenset({"false", "no", "off", "0"})

_KEY_UNSAFE = re.compile(r"[.=\[\]\s]")


# --------------------------------------------------------------- scalar values


def _parse_value(raw: str) -> Any:
    """A keyed-section value: JSON when it looks like JSON, else the string.

    ``json.loads`` is the arbiter of "looks like JSON" because everything it
    accepts is unambiguous, and everything it rejects (``#ff0000``,
    ``Segoe UI, sans-serif``) is exactly what should stay a string.
    """
    s = raw.strip()
    if not s:
        return ""
    try:
        return json.loads(s)
    except ValueError:
        pass
    low = s.lower()
    if low in ("true", "false"):          # JSON is case-sensitive; users are not
        return low == "true"
    if low in ("null", "none"):
        return None
    return s


def _as_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        low = v.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
    return None


def _coerce_cell(raw: str, quoted: bool) -> Any:
    """One ``[data]`` field.  Quoting is the user's "this is text" escape hatch."""
    if quoted:
        return raw
    s = raw.strip()
    if s == "" or s == _NO_VALUE:
        return None
    if s in ("true", "false"):
        return s == "true"
    return _maybe_number(s)


def _maybe_number(s: str) -> Any:
    """``"1.5"`` -> 1.5, ``"007"`` -> ``"007"``.

    Leading zeros mark an identifier (accession numbers, plate wells) and
    underscores are an int-literal feature no data file means to invoke; both
    stay text.  A token with no digit at all stays text too, which stops
    ``nan`` and ``inf`` from turning a taxon label into a float.
    """
    if "_" in s or not any(c.isdigit() for c in s):
        return s
    body = s[1:] if s[0] in "+-" else s
    if len(body) > 1 and body[0] == "0" and body[1].isdigit():
        return s
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


# ------------------------------------------------------------------- splitting


def _split_fields(line: str, sep: str) -> list[tuple[str, bool]]:
    """Split *line* on *sep*, honouring quotes.  Returns (text, was_quoted) pairs.

    A ``"`` opens a quoted field only at the start of a field: treating it as a
    toggle anywhere would mangle values such as ``5"`` that mean the character.
    """
    pattern = _SEPARATORS[sep]
    out: list[tuple[str, bool]] = []
    i, n = 0, len(line)
    while True:
        quoted = False
        buf: list[str] = []
        if i < n and line[i] == '"':
            quoted = True
            i += 1
            while i < n:
                if line[i] == '"':
                    if i + 1 < n and line[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(line[i])
                i += 1
        start = i
        while i < n and not pattern.match(line, i):
            i += 1
        tail = line[start:i]
        out.append(("".join(buf) + tail.strip(), True) if quoted
                   else (tail.strip(), False))
        if i >= n:
            return out
        m = pattern.match(line, i)
        i = m.end()                       # type: ignore[union-attr]
        if i >= n:                        # trailing separator: one empty field
            out.append(("", False))
            return out


def _detect_separator(line: str) -> str:
    """Tab, else comma, else a run of two or more spaces -- decided once.

    Detection looks only outside quoted regions, so a comma inside a quoted
    taxon name cannot promote a tab-separated file to CSV.
    """
    bare = _strip_quoted(line)
    if "\t" in bare:
        return "\t"
    if "," in bare:
        return ","
    return " "


def _strip_quoted(line: str) -> str:
    out: list[str] = []
    in_q = False
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch == '"':
            if in_q and i + 1 < n and line[i + 1] == '"':
                i += 2
                continue
            in_q = not in_q
        elif not in_q:
            out.append(ch)
        i += 1
    return "".join(out)


# ------------------------------------------------------------- dotted options


def _set_dotted(target: dict[str, Any], key: str, value: Any,
                sink: DiagnosticSink | None, line: int) -> None:
    """``border.width = 0.5`` becomes ``{"border": {"width": 0.5}}``."""
    parts = [p for p in key.split(".") if p]
    if not parts:
        return
    cur = target
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            if nxt is not None and sink is not None:
                sink.warn("annot.option-conflict",
                          f"option {p!r} was a scalar and is now a group", line=line)
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _flatten(prefix: str, value: Any) -> Iterable[tuple[str, Any]]:
    """Inverse of :func:`_set_dotted`, for the writer.

    A nested group whose member names contain a dot cannot be written with
    dotted keys without ambiguity, so such a group is emitted whole as JSON
    instead.  The top level has no such escape -- a dot in a top-level option
    name is what the grammar reserves for nesting -- so it always expands.
    """
    if isinstance(value, dict) and value:
        safe = all(isinstance(k, str) and not _KEY_UNSAFE.search(k) for k in value)
        if safe or not prefix:
            for k, v in value.items():
                yield from _flatten(f"{prefix}.{k}" if prefix else k, v)
            return
    yield prefix, value


# ---------------------------------------------------------------------- parse


def parse_annotation(text: str, *, sink: DiagnosticSink | None = None,
                     source: str | None = None) -> AnnotationTable:
    """Parse a ``.mytrack`` document.

    Problems are reported through *sink* and parsing continues; the one fatal
    case is a table that names no track type, because there is then nothing to
    build.  *source* is recorded on the table for error messages and is not
    part of the file text.
    """
    table = AnnotationTable(source=source)
    section = ""
    seen_data_section = False
    data_lines: list[tuple[int, str]] = []
    extras: dict[str, dict[str, Any]] = {}
    extra_lines: dict[str, list[str]] = {}
    seen_content = False
    type_line: int | None = None

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if not seen_content and stripped.startswith(MAGIC):
            seen_content = True
            _read_magic(table, stripped, sink, lineno)
            continue
        seen_content = True
        if stripped[0] in "#;":
            continue
        m = _SECTION_RE.match(stripped)
        if m:
            section = m.group(1).strip().lower()
            if section == "data":
                seen_data_section = True
            elif section not in _KNOWN_SECTIONS:
                if sink is not None:
                    sink.warn("annot.unknown-section",
                              f"unknown section [{section}]; kept as options",
                              line=lineno)
                extras.setdefault(section, {})
            continue
        if section == "data":
            data_lines.append((lineno, line))
            continue
        if not section:
            if sink is not None:
                sink.warn("annot.stray-line", "line outside any section, ignored",
                          line=lineno, context=stripped[:80])
            continue
        key, eq, value = stripped.partition("=")
        if not eq:
            if section in extras:
                extra_lines.setdefault(section, []).append(stripped)
            elif sink is not None:
                sink.warn("annot.bad-entry", "expected 'key = value'", line=lineno,
                          context=stripped[:80])
            continue
        key = _unquote(key.strip())
        value = value.strip()
        if section == "track":
            if key.lower() == "type":
                type_line = lineno
            _read_track(table, key, value, sink, lineno)
        elif section == "options":
            _set_dotted(table.options, key.lower(), _parse_value(value), sink, lineno)
        elif section == "columns":
            _read_columns(table, key, value, sink, lineno)
        elif section == "colors":
            _read_color(table, key, value, sink, lineno)
        elif section == "legend":
            _read_legend(table, key, value, sink, lineno)
        else:
            extras.setdefault(section, {})[key] = _parse_value(value)

    for name, lines in extra_lines.items():
        extras.setdefault(name, {})["_lines"] = lines
    for name, kv in extras.items():
        table.options[name] = kv

    if not table.track_type:
        raise ParseError("annotation table declares no [track] type",
                         line=type_line, context=source)

    _read_data(table, data_lines, sink)
    if not seen_data_section and sink is not None:
        sink.warn("annot.no-data", "no [data] section; the track will be empty")
    return table


def _read_magic(table: AnnotationTable, line: str, sink: DiagnosticSink | None,
                lineno: int) -> None:
    rest = line[len(MAGIC):].strip()
    if not rest:
        return
    try:
        table.version = int(rest.split()[0])
    except ValueError:
        if sink is not None:
            sink.warn("annot.bad-version", f"unreadable format version {rest!r}",
                      line=lineno)
        return
    if table.version > 1 and sink is not None:
        sink.info("annot.newer-version",
                  f"file declares format version {table.version}; "
                  "reading it as version 1", line=lineno)


def _unquote(text: str) -> str:
    """Strip one layer of quoting from a key or a free-text value.

    Both conventions are accepted: JSON escaping, which is what the writer
    emits, and the doubled-quote form of RFC 4180 that a hand-editing user is
    more likely to reach for.
    """
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            value = json.loads(text)
        except ValueError:
            return text[1:-1].replace('""', '"')
        if isinstance(value, str):
            return value
        return text[1:-1].replace('""', '"')
    return text


def _read_track(table: AnnotationTable, key: str, value: str,
                sink: DiagnosticSink | None, lineno: int) -> None:
    low = key.lower()
    if low == "type":
        table.track_type = value.lower()
    elif low == "title":
        table.title = _unquote(value)
    elif low == "id":
        table.track_id = _unquote(value)
    elif low == "match":
        v = value.lower()
        if v not in _MATCH_VALUES:
            if sink is not None:
                sink.warn("annot.bad-match",
                          f"match must be 'leaves' or 'all', got {value!r}",
                          line=lineno)
            v = "leaves"
        table.match = v
    else:
        if sink is not None:
            sink.warn("annot.unknown-key", f"unknown [track] key {key!r}; kept",
                      line=lineno)
        _set_dotted(table.options, f"track.{low}", _parse_value(value), sink, lineno)


def _read_columns(table: AnnotationTable, key: str, value: str,
                  sink: DiagnosticSink | None, lineno: int) -> None:
    if key.lower() != "names":
        if sink is not None:
            sink.warn("annot.unknown-key", f"unknown [columns] key {key!r}; kept",
                      line=lineno)
        _set_dotted(table.options, f"columns.{key.lower()}", _parse_value(value),
                    sink, lineno)
        return
    parsed = _parse_value(value)
    if isinstance(parsed, list):
        table.columns = [str(x) for x in parsed]
        return
    table.columns = [t for t, _ in _split_fields(value, ",")]


def _read_color(table: AnnotationTable, key: str, value: str,
                sink: DiagnosticSink | None, lineno: int) -> None:
    try:
        table.colors[key] = parse_color(value)
    except ValueError as exc:
        if sink is not None:
            sink.warn("annot.bad-color", str(exc), line=lineno)


def _read_legend(table: AnnotationTable, key: str, value: str,
                 sink: DiagnosticSink | None, lineno: int) -> None:
    low = key.lower()
    if low == "title":
        table.legend["title"] = _unquote(value)
        return
    if low == "show":
        b = _as_bool(value)
        if b is None:
            if sink is not None:
                sink.warn("annot.bad-bool",
                          f"legend show={value!r} is not a boolean", line=lineno)
            return
        table.legend["show"] = b
        return
    if low == "order":
        parsed = _parse_value(value)
        table.legend["order"] = ([str(x) for x in parsed] if isinstance(parsed, list)
                                 else [t for t, _ in _split_fields(value, ",") if t])
        return
    if sink is not None and low not in _LEGEND_KEYS:
        sink.warn("annot.unknown-key", f"unknown [legend] key {key!r}; kept",
                  line=lineno)
    table.legend[low] = _parse_value(value)


def _read_data(table: AnnotationTable, lines: list[tuple[int, str]],
               sink: DiagnosticSink | None) -> None:
    if not lines:
        return
    sep = _detect_separator(lines[0][1])
    rows = [(lineno, _split_fields(line, sep)) for lineno, line in lines]

    declared = bool(table.columns)
    if not declared:
        first = rows[0][1]
        head = first[0][0].strip().lower()
        if len(first) > 1 and head in _HEADER_KEYS and not first[0][1]:
            table.columns = [t for t, _ in first[1:]]
            rows = rows[1:]

    width = max((len(fields) for _, fields in rows), default=1)
    _widen_columns(table, width - 1, declared, sink)

    ncols = len(table.columns)
    for lineno, fields in rows:
        key = fields[0][0]
        if not key:
            if sink is not None:
                sink.warn("annot.empty-key", "record has no node key; skipped",
                          line=lineno)
            continue
        values: list[Any] = [_coerce_cell(t, q) for t, q in fields[1:]]
        if len(values) < ncols:
            values.extend([None] * (ncols - len(values)))
        if key in table.records and sink is not None:
            sink.warn("annot.duplicate-key",
                      f"duplicate record for {key!r}; the later one wins", line=lineno)
        table.records[key] = values


def _widen_columns(table: AnnotationTable, needed: int, declared: bool,
                   sink: DiagnosticSink | None) -> None:
    """Grow the column list to cover the widest record.

    A short ``[columns] names`` is a user slip, not a reason to throw the extra
    columns away, so the missing names are generated.
    """
    if needed <= len(table.columns):
        return
    if declared and sink is not None:
        sink.warn("annot.extra-columns",
                  f"data has {needed} value column(s) but only "
                  f"{len(table.columns)} name(s); the rest were named for you")
    while len(table.columns) < needed:
        i = len(table.columns) + 1
        table.columns.append("value" if i == 1 else f"value{i}")


# ---------------------------------------------------------------------- write


def _needs_quote(s: str, sep: str) -> bool:
    if s == "" or s != s.strip() or s == _NO_VALUE:
        return True
    if '"' in s or "\n" in s or "\t" in s:
        return True
    if _SEPARATORS[sep].search(s):
        return True
    # Anything the reader would turn into a non-string must be pinned as text.
    return s in ("true", "false") or not isinstance(_maybe_number(s), str)


def _quote(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def _format_cell(v: Any, sep: str) -> str:
    if v is None:
        return _NO_VALUE
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return _quote(v) if _needs_quote(v, sep) else v
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _format_value(v: Any) -> str:
    """A keyed-section value.  A string the reader would re-read as JSON is quoted."""
    if isinstance(v, str):
        if v != v.strip() or "\n" in v:
            return json.dumps(v)
        probe = _parse_value(v)
        return v if isinstance(probe, str) and probe == v else json.dumps(v)
    if isinstance(v, Color):
        return v.hex
    return json.dumps(v)


def _format_key(k: str) -> str:
    return _quote(k) if _KEY_UNSAFE.search(k) or '"' in k else k


def write_annotation(table: AnnotationTable) -> str:
    """Serialise *table* back to ``.mytrack`` text.

    The writer always separates data with tabs and always names the columns
    explicitly, so the reader never has to guess anything about its own output.
    """
    out: list[str] = [f"{MAGIC} {table.version}", ""]

    out.append("[track]")
    out.append(f"type = {table.track_type}")
    if table.title:
        out.append(f"title = {_format_value(table.title)}")
    if table.track_id:
        out.append(f"id = {_format_value(table.track_id)}")
    if table.match and table.match != "leaves":
        out.append(f"match = {table.match}")
    out.append("")

    if table.options:
        out.append("[options]")
        for key, value in _flatten("", table.options):
            out.append(f"{_format_key(key)} = {_format_value(value)}")
        out.append("")

    if table.columns:
        out.append("[columns]")
        names = [_quote(c) if _needs_quote(c, ",") else c for c in table.columns]
        out.append("names = " + ", ".join(names))
        out.append("")

    if table.colors:
        out.append("[colors]")
        for name, color in table.colors.items():
            out.append(f"{_format_key(name)} = {color.hex}")
        out.append("")

    if table.legend:
        out.append("[legend]")
        for key, value in table.legend.items():
            if key == "order" and isinstance(value, list):
                order = [_quote(str(x)) if _needs_quote(str(x), ",") else str(x)
                         for x in value]
                out.append("order = " + ", ".join(order))
            elif isinstance(value, bool):
                out.append(f"{_format_key(key)} = {'true' if value else 'false'}")
            else:
                out.append(f"{_format_key(key)} = {_format_value(value)}")
        out.append("")

    out.append("[data]")
    ncols = len(table.columns)
    for key, values in table.records.items():
        row = list(values)[:ncols] if ncols else list(values)
        row.extend([None] * (ncols - len(row)))
        cells = [_format_cell(key, "\t")]
        cells.extend(_format_cell(v, "\t") for v in row)
        out.append("\t".join(cells))
    return "\n".join(out) + "\n"

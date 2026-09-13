# SPDX-License-Identifier: MIT
"""Newick and NHX reading and writing.

The grammar implemented is the "Newick's 8:45" standard (Olsen 1990, the
informal description agreed by the Society for the Study of Evolution's
committee), widened to the superset real files actually contain: nested
``[...]`` comments (PAUP behaviour, inherited from NEXUS), the NHX v2.0 tag
block (Zmasek 1999, ``[&&NHX:key=value:...]``), and the BEAST/FigTree
``[&key=value,...]`` metacomment convention.

Two structural decisions matter more than anything else here.

*The scanner is a character state machine, not a regex.*  A regex cannot match
nested comments at all, and it gets quoted labels wrong: a quoted label ends at
the first *unpaired* quote, and ``''`` inside it is an escaped quote, which is
not a property ``'[^']*'`` can express.

*The parser keeps an explicit stack.*  A pectinate ("caterpillar") tree of
100 000 leaves nests 100 000 parentheses deep, so recursive descent crashes the
interpreter on exactly the files that matter most.  Writing uses an explicit
stack for the same reason.

Reading is lenient by design: everything recoverable is repaired and reported
through a :class:`~makeyourtree.core.diagnostics.DiagnosticSink`.  Only input with
no recoverable structure at all raises
:class:`~makeyourtree.core.errors.ParseError`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterator, NamedTuple

from ..core.diagnostics import DiagnosticSink
from ..core.errors import ParseError
from ..core.node import Node
from ..core.traversal import preorder
from ..core.tree import Tree
from ..style.color import parse_color

__all__ = ["read_newick", "read_newick_multi", "write_newick", "NEWICK_ID_KEY"]

NEWICK_ID_KEY = "ID"
"""NHX tag used to carry a MakeYourTree node id through a Newick round trip.

The NHX spec's own ``ND`` tag is left alone: real files use it for accessions
and gene-tree node names, and overwriting those would lose data.
"""

_SQ = "'"
_DQ = '"'
_STRUCT = "(),:;"
_STOP = frozenset("()[],:;" + _SQ)
_QUOTE_FOLLOWERS = frozenset("(),:;[]" + _SQ)

_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_PURE_NUMBER_RE = re.compile(r"\s*" + _NUMBER_RE.pattern + r"\s*\Z")
_COMPOSITE_RE = re.compile(
    r"\s*" + _NUMBER_RE.pattern + r"(?:/" + _NUMBER_RE.pattern + r")+\s*\Z")
_EDGE_NUM_RE = re.compile(r"\{(\d+)\}\Z")

# One key/value pair of the [&...] metacomment convention.  Keys there are not
# identifiers: real ones contain '%', '.', '(', ')', '+', '-' and spaces, so
# anything resembling ``\w+`` silently drops the HPD and probability fields that
# Bayesian samplers write.
_META_PAIR = re.compile(r'("[^"]*"+|[^,=\s][^,=]*?)\s*(?:=\s*(\{[^{}]*\}|"[^"]*"+|[^,]+))?\s*(?:,|;|$)')
# NHX fields are separated by ':' and may carry a ``{a,b}`` list value borrowed
# from the BEAST convention.
_NHX_FIELD = re.compile(r"([^=:]+)=(\{[^{}]*\}|[^:]*)(?::|$)")


# ------------------------------------------------------------------ scanning


class _Tok(NamedTuple):
    """One lexical token, carrying enough position to point a user at a byte."""

    kind: str          # '(' ')' ',' ':' ';' 'label' 'comment' 'eof'
    text: str
    quoted: bool
    line: int
    col: int
    pos: int


class _Scanner:
    """Character-driven tokeniser with unbounded lookahead through a buffer.

    Numbers are deliberately *not* lexed: ``2003`` is a perfectly good tip
    label, and only the parser knows whether it stands where a branch length is
    expected.  Everything unquoted is a label token; the parser converts.
    """

    __slots__ = ("text", "n", "i", "line", "bol", "nested", "sink", "_buf")

    def __init__(self, text: str, *, nested_comments: bool, sink: DiagnosticSink,
                 line0: int = 1) -> None:
        self.text = text
        self.n = len(text)
        self.i = 0
        self.line = line0
        self.bol = 0
        self.nested = nested_comments
        self.sink = sink
        self._buf: list[_Tok] = []

    # -- buffer ----------------------------------------------------------

    def peek(self, k: int = 0) -> _Tok:
        while len(self._buf) <= k:
            self._buf.append(self._scan())
        return self._buf[k]

    def next(self) -> _Tok:
        tok = self.peek(0)
        if tok.kind != "eof":
            self._buf.pop(0)
        return tok

    # -- scanning --------------------------------------------------------

    def _col(self, pos: int) -> int:
        return pos - self.bol + 1

    def _skip_space(self) -> None:
        t, n = self.text, self.n
        i = self.i
        while i < n:
            c = t[i]
            if c == "\n":
                self.line += 1
                i += 1
                self.bol = i
            elif c in " \t\v\f" or c <= "\x06":
                i += 1
            else:
                break
        self.i = i

    def _scan(self) -> _Tok:
        while True:
            self._skip_space()
            i = self.i
            if i >= self.n:
                return _Tok("eof", "", False, self.line, self._col(i), i)
            c = self.text[i]
            line, col = self.line, self._col(i)
            if c in _STRUCT:
                self.i = i + 1
                return _Tok(c, c, False, line, col, i)
            if c == "[":
                return self._scan_comment(line, col)
            if c == "]":
                # A closing bracket with no comment open: left behind when a
                # nested comment was written for a reader that nests and read by
                # one that does not.  Dropping it is the only way forward, and
                # it must consume a character or the scanner cannot advance.
                self.i = i + 1
                self.sink.warn("newick.stray-bracket",
                               "']' outside a comment; ignored", line=line, col=col)
                continue
            if c in (_SQ, _DQ):
                return self._scan_quoted(c, line, col)
            return self._scan_word(line, col)

    def _scan_comment(self, line: int, col: int) -> _Tok:
        """``[...]``, nested when the dialect allows it (PAUP/NEXUS do)."""
        t, n = self.text, self.n
        start = self.i
        i = start + 1
        depth = 1
        while i < n:
            c = t[i]
            if c == "\n":
                self.line += 1
                self.bol = i + 1
            elif c == "[" and self.nested:
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    self.i = i + 1
                    return _Tok("comment", t[start + 1:i], False, line, col, start)
            i += 1
        self.i = n
        self.sink.warn("newick.unterminated-comment",
                       "comment is not closed before end of input; closed it implicitly",
                       line=line, col=col)
        return _Tok("comment", t[start + 1:], False, line, col, start)

    def _scan_quoted(self, q: str, line: int, col: int) -> _Tok:
        """A quoted label.  ``''`` is an escaped quote; a lone quote ends it.

        Files written by tools that forgot to double an embedded apostrophe are
        common (``'John's'``).  When the character after a closing quote cannot
        legally follow a label, the quote is taken as literal text instead --
        that recovers the whole class without affecting well-formed input.
        """
        t, n = self.text, self.n
        start = self.i
        i = start + 1
        out: list[str] = []
        while i < n:
            c = t[i]
            if c == q:
                if i + 1 < n and t[i + 1] == q:
                    out.append(q)
                    i += 2
                    continue
                j = i + 1
                while j < n and t[j] in " \t\n":
                    j += 1
                if j < n and t[j] not in _QUOTE_FOLLOWERS:
                    self.sink.warn(
                        "newick.unescaped-quote",
                        "quote inside a quoted label was not doubled; read as literal",
                        line=line, col=col)
                    out.append(q)
                    i += 1
                    continue
                self.i = i + 1
                return _Tok("label", "".join(out), True, line, col, start)
            if c == "\n":
                self.line += 1
                self.bol = i + 1
            out.append(c)
            i += 1
        self.i = n
        self.sink.warn("newick.unterminated-quote",
                       "quoted label is not closed before end of input",
                       line=line, col=col)
        return _Tok("label", "".join(out), True, line, col, start)

    def _scan_word(self, line: int, col: int) -> _Tok:
        t, n = self.text, self.n
        start = self.i
        i = start
        while i < n:
            c = t[i]
            if c in _STOP or c.isspace() or c <= "\x06":
                break
            i += 1
        if i == start:  # never return a token that consumed nothing
            i += 1
            self.sink.warn("newick.unexpected-character",
                           f"unexpected {t[start]!r}; skipped", line=line, col=col)
        self.i = i
        return _Tok("label", t[start:i], False, line, col, start)


# ------------------------------------------------------------------ options


@dataclass(slots=True)
class _Opts:
    """Reader settings, bundled so the parser helpers stay readable."""

    preserve_underscores: bool = False
    nested_comments: bool = True
    internal_labels: str = "auto"
    keep_comments: bool = True
    read_ids: bool = True
    id_key: str = NEWICK_ID_KEY
    expect_semicolon: bool = True
    """False inside a NEXUS TREE command, where the ';' terminates the command
    and has already been consumed before the tree text is handed over."""


def _unescape_label(tok: _Tok, opts: _Opts) -> str:
    """Underscore-to-blank conversion applies to *unquoted* labels only.

    That asymmetry is normative: ``A_B`` means ``A B`` while ``'A_B'`` keeps its
    underscore.  It is also the single most common way a naive round trip
    corrupts a file, which is why it is switchable.
    """
    s = tok.text
    if tok.quoted or opts.preserve_underscores:
        return s
    return s.replace("_", " ")


# -------------------------------------------------------------- annotations


def _split_list(body: str) -> list[str]:
    """Split a ``{a,b,{c,d}}`` value on top-level commas, iteratively."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in body:
        if ch == "{":
            depth += 1
            cur.append(ch)
        elif ch == "}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur or out:
        out.append("".join(cur))
    return out


def _coerce(value: str) -> Any:
    """BEAST's coercion ladder: list, colour, boolean, int, float, string."""
    v = value.strip()
    if not v:
        return True
    if v.startswith("{") and v.endswith("}"):
        inner = v[1:-1].strip()
        if not inner:
            return ()
        return tuple(_coerce(part) for part in _split_list(inner))
    if len(v) >= 2 and v[0] == _DQ and v[-1] == _DQ:
        return v[1:-1]
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        f = float(v)
    except ValueError:
        return v
    return f if math.isfinite(f) else v


def _apply_style_hint(node: Node, key: str, value: Any) -> None:
    """Map the FigTree display keys onto MakeYourTree node styles.

    ``!color`` and ``!collapse`` are the two that change what a reader draws;
    the raw key stays in ``attrs`` so nothing is lost on the way out again.
    """
    if key == "!color" and isinstance(value, str):
        try:
            node.set_style(branch_color=parse_color(value))
        except ValueError:
            return
    elif key == "!collapse":
        node.collapsed = True


def _parse_nhx(node: Node, body: str, opts: _Opts, pending: dict[int, int],
               tok: _Tok, sink: DiagnosticSink) -> None:
    """``[&&NHX:key=value:...]`` -- the one unambiguous annotation dialect."""
    body = body.lstrip(":")
    if not body.strip():
        return
    for m in _NHX_FIELD.finditer(body):
        key = m.group(1).strip()
        if not key:
            continue
        raw = m.group(2)
        if key == "B":
            v = _coerce(raw)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                node.support = float(v)
                continue
        if key == "C":
            # rrr.ggg.bbb, decimal and dot separated -- not a hex colour.
            parts = raw.split(".")
            if len(parts) == 3 and all(p.strip().isdigit() for p in parts):
                r, g, b = (min(255, int(p)) for p in parts)
                node.set_style(branch_color=parse_color(f"#{r:02x}{g:02x}{b:02x}"))
        if key == "Co" and raw.strip().upper().startswith("Y"):
            node.collapsed = True
        if key == "W":
            v = _coerce(raw)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                node.set_style(branch_width=float(v))
        if opts.read_ids and key == opts.id_key:
            try:
                pending[id(node)] = int(raw)
                continue
            except ValueError:
                sink.warn("newick.bad-node-id",
                          f"NHX field {key}={raw!r} is not an integer node id",
                          line=tok.line, col=tok.col)
        node.attrs[key] = _coerce(raw)


def _parse_meta(node: Node, body: str) -> None:
    """``[&key=value,...]`` as written by BEAST, MrBayes and FigTree."""
    pos = 0
    n = len(body)
    while pos < n:
        m = _META_PAIR.match(body, pos)
        if m is None or m.end() == pos:
            pos += 1
            continue
        pos = m.end()
        key = m.group(1).strip()
        if key.startswith(_DQ) and key.endswith(_DQ) and len(key) > 1:
            key = key[1:-1]
        if not key:
            continue
        value = _coerce(m.group(2)) if m.group(2) is not None else True
        node.attrs[key] = value
        if key.startswith("!"):
            _apply_style_hint(node, key, value)


def _apply_comment(node: Node, tok: _Tok, opts: _Opts,
                   pending: dict[int, int], sink: DiagnosticSink) -> None:
    """Route one comment to annotations, to support, or to verbatim text.

    Producers disagree about which slot means what -- ``X[&a]:1`` is a node
    attribute in BEAST, ``X:[&a]1`` a branch attribute, and ``X:1[&a]`` a branch
    attribute in MrBayes and RAxML -- but a node and its parent edge share one
    ``attrs`` map here, so all four slots feed the same place.  Position does
    still decide one thing: a bare number only becomes support on a node that
    has children, which is the RAxML ``bipartitionsBranchLabels`` convention and
    never a numeric tip label.
    """
    body = tok.text
    stripped = body.strip()
    if stripped.startswith("&&"):
        _parse_nhx(node, stripped[2:].lstrip("NHXnhx"), opts, pending, tok, sink)
        return
    if stripped.startswith("&"):
        _parse_meta(node, stripped[1:])
        return
    if node.children and _PURE_NUMBER_RE.match(stripped):
        # RAxML bipartitionsBranchLabels style: the branch value lives in a
        # comment attached to the edge, which is where it semantically belongs.
        if node.support is None:
            node.support = float(stripped)
            return
    if opts.keep_comments:
        node.comment = body if node.comment is None else node.comment + body


# ------------------------------------------------------------------ parsing


def _read_length(sc: _Scanner, node: Node, sink: DiagnosticSink) -> None:
    """Parse the token after a ``:`` as a branch length, leniently.

    Negative and zero lengths are legal and common (NJ, BioNJ, least squares,
    hard polytomies) and are never clamped here -- the layout engine clamps for
    drawing while the model keeps the true value.
    """
    tok = sc.peek()
    if tok.kind != "label":
        sink.warn("newick.missing-length", "':' with no branch length after it",
                  line=tok.line, col=tok.col)
        return
    sc.next()
    text = tok.text.strip()
    m = _EDGE_NUM_RE.search(text)
    if m:
        node.attrs["edge_num"] = int(m.group(1))  # jplace edge numbering
        text = text[:m.start()]
    try:
        value = float(text)
    except ValueError:
        sink.warn("newick.bad-length", f"branch length {tok.text!r} is not a number",
                  line=tok.line, col=tok.col)
        node.attrs["length_raw"] = tok.text
        return
    if not math.isfinite(value):
        sink.warn("newick.bad-length", f"branch length {tok.text!r} is not finite",
                  line=tok.line, col=tok.col)
        node.attrs["length_raw"] = tok.text
        return
    node.branch_length = value
    _check_decimal_comma(sc, tok, text, sink)


def _check_decimal_comma(sc: _Scanner, tok: _Tok, text: str,
                         sink: DiagnosticSink) -> None:
    """Warn about ``:1,5`` -- a European decimal comma inside a branch length.

    This malformation is the dangerous one: the comma is the child separator, so
    the file parses silently with an extra tip instead of failing.
    """
    if "." in text or "e" in text.lower():
        return
    if sc.peek().kind != ",":
        return
    nxt = sc.peek(1)
    if nxt.kind != "label" or not nxt.text.isdigit():
        return
    if sc.peek(2).kind not in (",", ")"):
        return
    sink.warn("newick.decimal-comma",
              f"branch length {text!r} is followed by ',{nxt.text}' -- this looks "
              "like a decimal comma and has produced an extra child",
              line=tok.line, col=tok.col)


def _node_tail(sc: _Scanner, node: Node, opts: _Opts, pending: dict[int, int],
               sink: DiagnosticSink) -> None:
    """Label, branch length and the comments around them, for one node."""
    while sc.peek().kind == "comment":
        _apply_comment(node, sc.next(), opts, pending, sink)
    if sc.peek().kind == "label":
        tok = sc.next()
        parts = [_unescape_label(tok, opts)]
        while sc.peek().kind == "label" and not sc.peek().quoted:
            extra = sc.next()
            sink.warn("newick.space-in-label",
                      f"unquoted label {parts[0]!r} contains whitespace; joined "
                      f"with {extra.text!r}", line=extra.line, col=extra.col)
            parts.append(_unescape_label(extra, opts))
        name = " ".join(parts)
        node.name = name if name != "" else None
    while sc.peek().kind == "comment":
        _apply_comment(node, sc.next(), opts, pending, sink)
    if sc.peek().kind == ":":
        sc.next()
        while sc.peek().kind == "comment":
            _apply_comment(node, sc.next(), opts, pending, sink)
        _read_length(sc, node, sink)
    while sc.peek().kind == "comment":
        _apply_comment(node, sc.next(), opts, pending, sink)


def _parse_subtree(sc: _Scanner, opts: _Opts, pending: dict[int, int],
                   sink: DiagnosticSink) -> Node:
    """One tree, parsed with an explicit stack.

    The stack holds the chain of open parentheses.  ``(`` pushes and descends,
    ``,`` starts a sibling under the current parent, ``)`` pops and then parses
    the closed node's own label and length.  No Python frame is consumed per
    level, so depth is limited only by memory.
    """
    root = Node()
    node = root
    stack: list[Node] = []
    while True:
        tok = sc.peek()
        if tok.kind == "(":
            if sc.peek(1).kind == ")":
                sc.next()
                sc.next()
                sink.warn("newick.empty-group",
                          "'()' has no children; read as an unnamed leaf",
                          line=tok.line, col=tok.col)
            else:
                sc.next()
                _warn_empty_child(sc, sink)
                child = Node()
                node.add_child(child)
                stack.append(node)
                node = child
                continue
        _node_tail(sc, node, opts, pending, sink)
        while stack and sc.peek().kind == ")":
            sc.next()
            node = stack.pop()
            _node_tail(sc, node, opts, pending, sink)
        if stack and sc.peek().kind == ",":
            sc.next()
            _warn_empty_child(sc, sink)
            node = stack[-1].add_child(Node())
            continue
        break
    if stack:
        tok = sc.peek()
        sink.warn("newick.unclosed-parens",
                  f"{len(stack)} unclosed parenthesis(es) at end of tree",
                  line=tok.line, col=tok.col)
    return root


def _warn_empty_child(sc: "_Scanner", sink: DiagnosticSink) -> None:
    """Note a comma with nothing before or after it.

    ``(A,,B)`` is accepted -- refusing a readable file is almost never what the
    user wants -- but it is reported at warning level, the same as ``()``,
    because the repair changes the data rather than only the syntax: the tree
    gains an unnamed tip, so the taxon count a reader quotes from the figure is
    one higher than the file was meant to contain.
    """
    tok = sc.peek()
    if tok.kind in (",", ")"):
        sink.warn("newick.empty-child",
                  "nothing between the commas; read as an unnamed leaf",
                  line=tok.line, col=tok.col)


def _resolve_internal_labels(root: Node, opts: _Opts, sink: DiagnosticSink,
                             line: int) -> None:
    """Decide whether a bare internal label is a clade name or a support value.

    Newick has no slot for branch metadata, so most programs write bootstrap
    percentages into the internal-node label.  The rule here: a label on a node
    that has children and is not the root, which parses as a single number,
    is support; anything else is a name.  Leaves are never reinterpreted --
    numeric sample identifiers as tip labels are entirely normal.

    ``internal_labels='name'`` switches the heuristic off, ``'support'``
    forces it and stays quiet, ``'auto'`` forces it and says so.
    """
    mode = opts.internal_labels
    if mode not in ("auto", "name", "support"):
        raise ValueError(f"internal_labels must be auto/name/support, not {mode!r}")
    if root.support is not None:
        # Support describes the edge above a node and the root has none, so a
        # value that landed there came from a bracket comment or an NHX B tag
        # that the writer had nowhere to put.  Keep it, but not as support.
        root.attrs.setdefault("root_support", root.support)
        root.support = None
    numeric = 0
    for n in preorder(root):
        raw = n.name
        if raw is None or n is root or not n.children:
            continue
        text = raw.strip()
        if not text:
            continue
        if _PURE_NUMBER_RE.match(text):
            if mode == "name":
                continue
            value = float(text)
            if n.support is None:
                n.support = value
                n.name = None
            else:
                # Both slots carried a value: keep both rather than pick.
                n.attrs.setdefault("label_support", value)
            numeric += 1
        elif _COMPOSITE_RE.match(text):
            # IQ-TREE writes 'SH-aLRT/UFboot' as one label.  It is not a single
            # number, so it stays the name; the parts are exposed for tracks.
            n.attrs.setdefault(
                "support_values",
                tuple(float(p) for p in text.split("/")))
    if numeric and mode == "auto":
        # Named in terms of the choice, not of this function's keyword: the
        # people who read this are using the command line or the application,
        # where a Python argument is not something they can pass.
        sink.info("newick.internal-label-ambiguous",
                  f"{numeric} internal label(s) parse as numbers and were read "
                  f"as branch support. If they are names, reopen the file with "
                  f"internal labels set to 'name'",
                  line=line)


def _assign_ids(root: Node, wanted: dict[int, int], sink: DiagnosticSink) -> None:
    """Apply node ids recovered from the NHX id field, keeping them unique."""
    used: set[int] = set()
    nodes = list(preorder(root))
    for n in nodes:
        want = wanted.get(id(n))
        if want is not None and want >= 0 and want not in used:
            n.id = want
            used.add(want)
        else:
            n.id = -1
            if want is not None:
                sink.warn("newick.duplicate-node-id",
                          f"node id {want} appears more than once; reassigned")
    nxt = max(used) + 1 if used else 0
    for n in nodes:
        if n.id < 0:
            n.id = nxt
            nxt += 1


def _read_trees(text: str, opts: _Opts, sink: DiagnosticSink, *,
                line0: int = 1, name: str | None = None) -> list[Tree]:
    """Parse every tree in *text*.  Shared by the Newick and NEXUS readers."""
    sc = _Scanner(text, nested_comments=opts.nested_comments, sink=sink, line0=line0)
    trees: list[Tree] = []
    while True:
        rooting: bool | None = None
        while sc.peek().kind == "comment":
            body = sc.next().text.strip().lower()
            if body in ("&r", "r"):
                rooting = True
            elif body in ("&u", "u"):
                rooting = False
        tok = sc.peek()
        if tok.kind == "eof":
            break
        if tok.kind == ";":
            sc.next()
            sink.info("newick.empty-tree", "stray ';' skipped",
                      line=tok.line, col=tok.col)
            continue
        if tok.kind in (")", ","):
            sc.next()
            sink.warn("newick.unexpected-token",
                      f"unexpected {tok.text!r} outside a tree; skipped",
                      line=tok.line, col=tok.col)
            continue
        pending: dict[int, int] = {}
        root = _parse_subtree(sc, opts, pending, sink)
        end = sc.peek()
        if end.kind == ";":
            sc.next()
        elif end.kind == "eof":
            if opts.expect_semicolon:
                sink.info("newick.missing-semicolon",
                          "last tree has no terminating ';'",
                          line=end.line, col=end.col)
        else:
            sink.warn("newick.trailing-garbage",
                      f"unexpected {end.text!r} where ';' was expected; skipping to "
                      "the next ';'", line=end.line, col=end.col)
            while sc.peek().kind not in (";", "eof"):
                sc.next()
            if sc.peek().kind == ";":
                sc.next()
        _resolve_internal_labels(root, opts, sink, tok.line)
        if pending:
            _assign_ids(root, pending, sink)
        declared = rooting is not None
        if rooting is None:
            # No [&R]/[&U]: fall back to the PHYLIP convention that a root with
            # three or more children is an unrooted trifurcation.
            rooting = len(root.children) <= 2
        tree = Tree(root, name=name, rooted=bool(rooting))
        tree.metadata["rooting_declared"] = declared
        tree.refresh()
        trees.append(tree)
    return trees


def read_newick_multi(text: str, *, sink: DiagnosticSink | None = None,
                      preserve_underscores: bool = False,
                      nested_comments: bool = True,
                      internal_labels: str = "auto",
                      keep_comments: bool = True,
                      read_ids: bool = True,
                      id_key: str = NEWICK_ID_KEY,
                      **_ignored: Any) -> list[Tree]:
    """Read every tree in a Newick or NHX string.

    Trees are separated by semicolons at parenthesis depth 0; a file may hold
    thousands and they may wrap lines freely, so nothing here is line oriented.
    """
    sink = sink if sink is not None else DiagnosticSink()
    opts = _Opts(preserve_underscores=preserve_underscores,
                 nested_comments=nested_comments, internal_labels=internal_labels,
                 keep_comments=keep_comments, read_ids=read_ids, id_key=id_key)
    return _read_trees(text, opts, sink)


def read_newick(text: str, **kw: Any) -> Tree:
    """Read the first tree in a Newick or NHX string."""
    trees = read_newick_multi(text, **kw)
    if not trees:
        raise ParseError("no tree found in Newick input")
    return trees[0]


# ------------------------------------------------------------------ writing


def _fmt_num(v: float, precision: int | None) -> str:
    """Format so that reading the result back yields the same float.

    ``repr`` gives the shortest string that round-trips exactly, which is what a
    round trip through a project file needs; ``precision`` overrides it when the
    user wants a tidy, lossy file.
    """
    if precision is not None:
        return f"{v:.{precision}g}"
    if v == int(v) and abs(v) < 1e16:
        return str(int(v))
    return repr(v)


def _quoted(s: str) -> str:
    return _SQ + s.replace(_SQ, _SQ + _SQ) + _SQ


def _label_text(name: str, quote_style: str, preserve_underscores: bool) -> str:
    """Quote a label only when it would otherwise change meaning.

    A label whose only offending character is a space is written with
    underscores instead: that is the traditional, maximally compatible form and
    it round-trips through every reader that follows the standard.
    """
    if quote_style == "always":
        return _quoted(name)
    special = any(c in "()[]:;," or c == _SQ or (c.isspace() and c != " ")
                  for c in name)
    if quote_style == "never":
        return name if preserve_underscores else name.replace(" ", "_")
    if special:
        return _quoted(name)
    underscore = "_" in name and not preserve_underscores
    if " " in name:
        return _quoted(name) if underscore else name.replace(" ", "_")
    return _quoted(name) if underscore else name


def _nhx_value(v: Any) -> str:
    """NHX defines no escape, so ``:`` and ``]`` must be removed, not escaped."""
    if isinstance(v, bool):
        text = "true" if v else "false"
    elif isinstance(v, float):
        text = _fmt_num(v, None)
    elif isinstance(v, (tuple, list)):
        text = "{" + ",".join(_nhx_value(x) for x in v) + "}"
    else:
        text = str(v)
    return text.replace(":", "_").replace("]", "").replace("[", "")


def _nhx_block(node: Node, attrs: bool, node_ids: bool, id_key: str,
               extra: list[str]) -> str:
    fields: list[str] = list(extra)
    if attrs:
        for key, value in node.attrs.items():
            if key.startswith("_") or key == id_key:
                continue
            fields.append(f"{key}={_nhx_value(value)}")
    if node_ids:
        fields.append(f"{id_key}={node.id}")
    return "[&&NHX:" + ":".join(fields) + "]" if fields else ""


def _node_text(node: Node, is_root: bool, lengths: bool, support: bool,
               internal_labels: bool, attrs: bool, node_ids: bool,
               quote_style: str, precision: int | None,
               preserve_underscores: bool, id_key: str) -> str:
    out: list[str] = []
    label: str | None = None
    support_text: str | None = None
    if support and node.children and not is_root and node.support is not None:
        support_text = _fmt_num(node.support, precision)
    if node.name and (internal_labels or not node.children):
        label = node.name
    elif support_text is not None:
        label, support_text = support_text, None
    if label:
        out.append(_label_text(label, quote_style, preserve_underscores))
    extra: list[str] = []
    if support_text is not None:
        if attrs:
            # NHX has the one branch-support slot that is never ambiguous.
            extra.append(f"B={support_text}")
        else:
            # The name took the label slot, so the value goes in a bracket
            # comment on the branch -- the RAxML branch-label convention, and
            # the placement Czech et al. (2017) argue is the correct one.
            out.append(f"[{support_text}]")
    if lengths and node.branch_length is not None:
        out.append(":" + _fmt_num(node.branch_length, precision))
    block = _nhx_block(node, attrs, node_ids, id_key, extra)
    if block:
        out.append(block)
    return "".join(out)


def write_newick(tree: Tree | Node, *, lengths: bool = True, support: bool = True,
                 internal_labels: bool = True, attrs: bool = False,
                 node_ids: bool = False, quote_style: str = "auto",
                 precision: int | None = None, preserve_underscores: bool = False,
                 rooting: bool = False, id_key: str = NEWICK_ID_KEY,
                 terminator: str = ";") -> str:
    """Serialise a tree to Newick, optionally with an NHX annotation block.

    Written with an explicit stack, like the parser and for the same reason.

    ``node_ids`` emits the MakeYourTree node id as an NHX field so a project file
    can be re-read with its style and annotation keys still pointing at the
    right nodes.  ``precision`` defaults to shortest-exact formatting, which is
    what makes ``read -> write -> read`` return identical branch lengths.

    A node carrying both a name and a support value writes the name -- the
    support would be indistinguishable from a clade name on the way back in.
    Turn on ``attrs`` to have it emitted as the unambiguous NHX ``B`` tag too.
    """
    if quote_style not in ("auto", "always", "never"):
        raise ValueError(f"quote_style must be auto/always/never, not {quote_style!r}")
    root = tree.root if isinstance(tree, Tree) else tree
    out: list[str] = []
    if rooting:
        out.append("[&R] " if getattr(tree, "rooted", True) else "[&U] ")
    stack: list[list[Any]] = [[root, -1]]
    while stack:
        frame = stack[-1]
        node, i = frame[0], frame[1]
        if i < 0:
            if node.children:
                out.append("(")
            frame[1] = 0
            continue
        if i < len(node.children):
            if i:
                out.append(",")
            frame[1] = i + 1
            stack.append([node.children[i], -1])
            continue
        if node.children:
            out.append(")")
        out.append(_node_text(node, node is root, lengths, support, internal_labels,
                              attrs, node_ids, quote_style, precision,
                              preserve_underscores, id_key))
        stack.pop()
    out.append(terminator)
    return "".join(out)


def iter_newick(trees: list[Tree], **kw: Any) -> Iterator[str]:
    """Serialise many trees lazily, one string each, without joining them."""
    for t in trees:
        yield write_newick(t, **kw)

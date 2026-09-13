# SPDX-License-Identifier: MIT
"""NEXUS reading and writing.

Implements the file format of Maddison, Swofford & Maddison, "NEXUS: an
extensible file format for systematic information", Syst. Biol. 46:590-621
(1997), restricted to what a tree viewer needs: the TAXA block, the TREES block
with its TRANSLATE table, and the ``[&R]``/``[&U]`` rooting command comments.
Every other block is skipped with the tokeniser rather than parsed, which is the
extensibility mechanism the standard itself prescribes -- a reader must not fail
on a block it does not know.

The lexical layer follows Appendix 1 of that paper: words may be single-quoted
with ``''`` as the escaped quote, underscores are equivalent to blanks, comments
are square-bracketed and nest, and case is insignificant.  One deliberate
deviation: ``ASSUMP[c]TIONS`` is specified to read as one word, but every
program that writes ``[&...]`` annotations into a tree relies on a comment
*ending* the token it follows.  Comments are therefore separate tokens here,
which is what makes ``A[&x=1]:0.1`` parse the way its author meant.

Tree specifications are not re-lexed: the substring between ``=`` and the
command's terminating semicolon is handed to the Newick reader, so the two
formats can never drift apart in their handling of labels, lengths or
annotations.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, NamedTuple

from ..core.diagnostics import DiagnosticSink
from ..core.errors import ParseError
from ..core.traversal import preorder
from ..core.tree import Tree
from .newick import _Opts, _read_trees, write_newick

__all__ = ["read_nexus", "write_nexus"]

_SQ = "'"
_DQ = '"'
_PUNCT = "();,=*"
_NEXUS_PUNCT = frozenset("()[]{}/\\,;:=*'\"`+-<>")
_BLOCK_END = ("end", "endblock")
_ALL_DIGITS = re.compile(r"\d+\Z")


class _Tok(NamedTuple):
    kind: str      # 'word' | 'punct' | 'comment' | 'eof'
    text: str
    quoted: bool
    line: int
    pos: int


class _Scanner:
    """NEXUS tokeniser: quotes, nested comments, punctuation, whitespace.

    ASCII 0-6 count as whitespace per the standard; files that have been through
    a binary-unsafe pipeline pick those bytes up, and treating them as
    separators is better than failing.
    """

    __slots__ = ("text", "n", "i", "line", "sink", "underscores", "_buf")

    def __init__(self, text: str, *, sink: DiagnosticSink,
                 preserve_underscores: bool = False) -> None:
        self.text = text
        self.n = len(text)
        self.i = 0
        self.line = 1
        self.sink = sink
        self.underscores = preserve_underscores
        self._buf: list[_Tok] = []

    def peek(self, k: int = 0) -> _Tok:
        while len(self._buf) <= k:
            self._buf.append(self._scan())
        return self._buf[k]

    def next(self) -> _Tok:
        tok = self.peek(0)
        if tok.kind != "eof":
            self._buf.pop(0)
        return tok

    def _scan(self) -> _Tok:
        t, n = self.text, self.n
        i = self.i
        while i < n:
            c = t[i]
            if c == "\n":
                self.line += 1
                i += 1
            elif c.isspace() or c <= "\x06":
                i += 1
            else:
                break
        self.i = i
        if i >= n:
            return _Tok("eof", "", False, self.line, i)
        c = t[i]
        line = self.line
        if c == "[":
            return self._comment(line)
        if c == "]":
            # Unbalanced close bracket: consume it so the scanner always makes
            # progress, and let the block loop carry on.
            self.i = i + 1
            self.sink.warn("nexus.stray-bracket", "']' outside a comment; ignored",
                           line=line)
            return _Tok("punct", "]", False, line, i)
        if c in _PUNCT:
            self.i = i + 1
            return _Tok("punct", c, False, line, i)
        if c in (_SQ, _DQ):
            return self._quoted(c, line)
        start = i
        while i < n:
            c = t[i]
            if c in _PUNCT or c in "[]" or c in (_SQ, _DQ) or c.isspace() or c <= "\x06":
                break
            i += 1
        self.i = i
        word = t[start:i]
        if not self.underscores:
            word = word.replace("_", " ")
        return _Tok("word", word, False, line, start)

    def _comment(self, line: int) -> _Tok:
        t, n = self.text, self.n
        start = self.i
        i = start + 1
        depth = 1
        while i < n:
            c = t[i]
            if c == "\n":
                self.line += 1
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    self.i = i + 1
                    return _Tok("comment", t[start + 1:i], False, line, start)
            i += 1
        self.i = n
        self.sink.warn("nexus.unterminated-comment",
                       "comment is not closed before end of file", line=line)
        return _Tok("comment", t[start + 1:], False, line, start)

    def _quoted(self, q: str, line: int) -> _Tok:
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
                self.i = i + 1
                return _Tok("word", "".join(out), True, line, start)
            if c == "\n":
                self.line += 1
            out.append(c)
            i += 1
        self.i = n
        self.sink.warn("nexus.unterminated-quote",
                       "quoted word is not closed before end of file", line=line)
        return _Tok("word", "".join(out), True, line, start)


# ------------------------------------------------------------------ reading


def _skip_command(sc: _Scanner) -> None:
    """Consume tokens up to and including the next command-terminating ';'."""
    while True:
        tok = sc.next()
        if tok.kind == "eof":
            return
        if tok.kind == "punct" and tok.text == ";":
            return


def _skip_block(sc: _Scanner, block: str, sink: DiagnosticSink) -> None:
    """Skip an unrecognised block to its END, using the tokeniser.

    Searching the raw text for ``END;`` is the classic bug: a quoted label or a
    comment containing the word ends the block early.  Going through the
    tokeniser makes both cases safe.
    """
    while True:
        tok = sc.next()
        if tok.kind == "eof":
            sink.warn("nexus.unterminated-block",
                      f"block {block!r} has no END; reached end of file")
            return
        if tok.kind == "word" and not tok.quoted and tok.text.lower() in _BLOCK_END:
            if sc.peek().kind == "punct" and sc.peek().text == ";":
                sc.next()
            return


def _read_taxa_block(sc: _Scanner, sink: DiagnosticSink) -> list[str]:
    """TAXA: DIMENSIONS NTAX=n; TAXLABELS a b c;  Taxon number is position."""
    labels: list[str] = []
    ntax: int | None = None
    while True:
        tok = sc.next()
        if tok.kind == "eof":
            sink.warn("nexus.unterminated-block", "TAXA block has no END;")
            break
        if tok.kind == "punct":
            continue
        if tok.kind == "comment":
            continue
        word = tok.text.lower()
        if not tok.quoted and word in _BLOCK_END:
            if sc.peek().kind == "punct" and sc.peek().text == ";":
                sc.next()
            break
        if not tok.quoted and word == "dimensions":
            while True:
                t = sc.next()
                if t.kind in ("eof",) or (t.kind == "punct" and t.text == ";"):
                    break
                if t.kind == "word" and t.text.lower() == "ntax":
                    if sc.peek().kind == "punct" and sc.peek().text == "=":
                        sc.next()
                    v = sc.next()
                    if v.kind == "word" and v.text.strip().isdigit():
                        ntax = int(v.text)
        elif not tok.quoted and word == "taxlabels":
            while True:
                t = sc.next()
                if t.kind == "eof" or (t.kind == "punct" and t.text == ";"):
                    break
                if t.kind == "word":
                    labels.append(t.text)
        else:
            _skip_command(sc)
    if ntax is not None and labels and ntax != len(labels):
        sink.warn("nexus.ntax-mismatch",
                  f"DIMENSIONS NTAX={ntax} but {len(labels)} TAXLABELS were given")
    return labels


def _read_translate(sc: _Scanner, sink: DiagnosticSink) -> dict[str, str]:
    """TRANSLATE key taxon, key taxon, ... ;

    Tolerates the three malformations seen in the wild: a trailing comma before
    the semicolon, ``=`` used as the pair separator, and pairs separated only by
    whitespace.
    """
    table: dict[str, str] = {}
    words: list[str] = []
    while True:
        tok = sc.next()
        if tok.kind == "eof" or (tok.kind == "punct" and tok.text == ";"):
            break
        if tok.kind == "word":
            words.append(tok.text)
    for i in range(0, len(words) - 1, 2):
        key, value = words[i], words[i + 1]
        if key in table and table[key] != value:
            sink.warn("nexus.duplicate-translate-key",
                      f"TRANSLATE key {key!r} is defined twice; kept the first")
            continue
        table[key] = value
    if len(words) % 2:
        sink.warn("nexus.odd-translate",
                  f"TRANSLATE has an unpaired entry {words[-1]!r}; ignored")
    return table


def _apply_translate(tree: Tree, table: dict[str, str], taxa: list[str],
                     sink: DiagnosticSink) -> None:
    """Resolve tree labels through TRANSLATE, then by taxon number.

    Resolution order is normative: a TRANSLATE key wins over the numeric
    position, because BEAST and PAUP write translate keys in tree-internal order
    that need not match TAXLABELS -- using the index first silently relabels the
    whole tree.
    """
    unknown = 0
    for node in preorder(tree.root):
        name = node.name
        if not name:
            continue
        if name in table:
            node.name = table[name]
        elif _ALL_DIGITS.match(name):
            idx = int(name)
            if 1 <= idx <= len(taxa):
                node.name = taxa[idx - 1]
            elif table:
                unknown += 1
        elif table and not node.children and name not in taxa:
            unknown += 1
    if unknown:
        sink.warn("nexus.unknown-taxon",
                  f"{unknown} tree label(s) are in neither the TRANSLATE table nor "
                  "TAXLABELS; kept them as literal labels")
    tree.reindex()


def _read_tree_command(sc: _Scanner, opts: _Opts, sink: DiagnosticSink) -> list[Tree]:
    """``TREE [*] name = [&R] <newick> ;``"""
    name: str | None = None
    rooting: bool | None = None
    eq: _Tok | None = None
    while True:
        tok = sc.next()
        if tok.kind == "eof":
            sink.warn("nexus.truncated-tree", "TREE command ends the file", line=tok.line)
            return []
        if tok.kind == "comment":
            body = tok.text.strip().lower()
            if body in ("&r", "r"):
                rooting = True
            elif body in ("&u", "u"):
                rooting = False
            continue
        if tok.kind == "punct":
            if tok.text == "*":
                continue          # marks the default tree; nothing to do here
            if tok.text == "=":
                eq = tok
                break
            if tok.text == ";":
                sink.warn("nexus.tree-without-body",
                          f"TREE {name or '?'} has no '=' and no tree", line=tok.line)
                return []
            continue
        name = tok.text if name is None else f"{name} {tok.text}"
    start = eq.pos + 1
    line0 = eq.line
    end = sc.n
    while True:
        tok = sc.next()
        if tok.kind == "eof":
            sink.info("nexus.missing-semicolon",
                      f"TREE {name or '?'} is not terminated by ';'", line=tok.line)
            break
        if tok.kind == "punct" and tok.text == ";":
            end = tok.pos
            break
    trees = _read_trees(sc.text[start:end], opts, sink, line0=line0, name=name)
    if len(trees) > 1:
        sink.warn("nexus.multiple-trees-in-command",
                  f"TREE {name or '?'} holds {len(trees)} trees", line=line0)
    for tree in trees:
        if rooting is not None:
            tree.rooted = rooting
            tree.metadata["rooting_declared"] = True
    return trees


def read_nexus(text: str, *, sink: DiagnosticSink | None = None,
               preserve_underscores: bool = False,
               internal_labels: str = "auto",
               keep_comments: bool = True,
               read_ids: bool = True,
               **_ignored: Any) -> list[Tree]:
    """Read every tree in a NEXUS file.

    A missing ``#NEXUS`` header is a warning, not an error: pipelines strip it,
    and the block structure is unambiguous without it.
    """
    sink = sink if sink is not None else DiagnosticSink()
    sc = _Scanner(text, sink=sink, preserve_underscores=preserve_underscores)
    opts = _Opts(preserve_underscores=preserve_underscores, nested_comments=True,
                 internal_labels=internal_labels, keep_comments=keep_comments,
                 read_ids=read_ids, expect_semicolon=False)
    head = sc.peek()
    if head.kind == "word" and head.text.lower().startswith("#nexus"):
        sc.next()
    else:
        sink.warn("nexus.missing-header",
                  "file does not start with #NEXUS; read as NEXUS anyway")
    taxa: list[str] = []
    trees: list[Tree] = []
    seen_block = False
    while True:
        tok = sc.next()
        if tok.kind == "eof":
            break
        if tok.kind != "word" or tok.quoted or tok.text.lower() != "begin":
            continue
        name_tok = sc.next()
        if name_tok.kind != "word":
            sink.warn("nexus.bad-block", "BEGIN is not followed by a block name",
                      line=name_tok.line)
            continue
        block = name_tok.text.strip().lower()
        if sc.peek().kind == "punct" and sc.peek().text == ";":
            sc.next()
        seen_block = True
        if block == "taxa":
            taxa.extend(_read_taxa_block(sc, sink))
        elif block == "trees":
            trees.extend(_read_trees_block(sc, taxa, opts, sink))
        else:
            _skip_block(sc, block, sink)
    if not seen_block:
        raise ParseError("no NEXUS block found in input")
    for tree in trees:
        tree.metadata.setdefault("taxa", list(taxa))
    return trees


def _read_trees_block(sc: _Scanner, taxa: list[str], opts: _Opts,
                      sink: DiagnosticSink) -> list[Tree]:
    table: dict[str, str] = {}
    out: list[Tree] = []
    while True:
        tok = sc.next()
        if tok.kind == "eof":
            sink.warn("nexus.unterminated-block", "TREES block has no END;")
            break
        if tok.kind in ("comment", "punct"):
            continue
        word = tok.text.lower()
        if not tok.quoted and word in _BLOCK_END:
            if sc.peek().kind == "punct" and sc.peek().text == ";":
                sc.next()
            break
        if not tok.quoted and word == "translate":
            if out:
                sink.warn("nexus.late-translate",
                          "TRANSLATE appears after a TREE command", line=tok.line)
            table.update(_read_translate(sc, sink))
        elif not tok.quoted and word in ("tree", "utree"):
            new = _read_tree_command(sc, opts, sink)
            if word == "utree":
                for tree in new:
                    tree.rooted = False
            for tree in new:
                if table or taxa:
                    _apply_translate(tree, table, taxa, sink)
                tree.refresh()
            out.extend(new)
        else:
            _skip_command(sc)
    return out


# ------------------------------------------------------------------ writing


def _nexus_token(s: str, *, preserve_underscores: bool = False) -> str:
    """Quote a NEXUS word when the standard's lexical rules demand it.

    An all-digit word must be quoted because object names may not consist only
    of digits, and an unquoted underscore would be read back as a blank.
    """
    if s == "":
        return _SQ + _SQ
    if _ALL_DIGITS.match(s):
        return _SQ + s + _SQ
    if any(c in _NEXUS_PUNCT or (c.isspace() and c != " ") for c in s):
        return _SQ + s.replace(_SQ, _SQ + _SQ) + _SQ
    if "_" in s and not preserve_underscores:
        return _SQ + s + _SQ
    return s.replace(" ", "_")


def _tip_labels(trees: list[Tree]) -> list[str]:
    """Distinct leaf labels in first-appearance order, which TRANSLATE numbers."""
    seen: dict[str, None] = {}
    for tree in trees:
        for leaf in tree.leaves:
            if leaf.name:
                seen.setdefault(leaf.name, None)
    return list(seen)


def _use_translate(trees: list[Tree], labels: list[str]) -> bool:
    """A TRANSLATE table pays for itself only when it makes the file smaller."""
    if not labels:
        return False
    quoted = [_nexus_token(x) for x in labels]
    index_cost = {x: len(str(i + 1)) for i, x in enumerate(labels)}
    occurrences = sum(1 for tree in trees for leaf in tree.leaves if leaf.name)
    plain = sum(len(_nexus_token(leaf.name))
                for tree in trees for leaf in tree.leaves if leaf.name)
    translated = sum(index_cost[leaf.name]
                     for tree in trees for leaf in tree.leaves if leaf.name)
    table = sum(len(q) + 8 for q in quoted)
    return occurrences > 0 and translated + table < plain


def write_nexus(trees: Tree | Iterable[Tree], *, translate: bool | None = None,
                taxa_block: bool = True, rooting: bool = True,
                tree_names: bool = True, indent: str = "    ",
                **newick_kw: Any) -> str:
    """Serialise trees as a NEXUS file with a TAXA and a TREES block.

    ``translate=None`` emits a TRANSLATE table when it shortens the file, which
    it does for anything but a handful of short labels.  ``[&R]``/``[&U]`` is
    always written when *rooting* is set: plain Newick carries no rooting flag,
    and a rooted tree read back as unrooted changes what the file means.
    """
    items = [trees] if isinstance(trees, Tree) else list(trees)
    labels = _tip_labels(items)
    use_translate = _use_translate(items, labels) if translate is None else bool(translate)
    lines: list[str] = ["#NEXUS", ""]
    if taxa_block and labels:
        lines.append("BEGIN TAXA;")
        lines.append(f"{indent}DIMENSIONS NTAX={len(labels)};")
        lines.append(f"{indent}TAXLABELS")
        for label in labels:
            lines.append(f"{indent}{indent}{_nexus_token(label)}")
        lines.append(f"{indent}{indent};")
        lines.append("END;")
        lines.append("")
    lines.append("BEGIN TREES;")
    key_of: dict[str, str] = {}
    if use_translate:
        key_of = {label: str(i + 1) for i, label in enumerate(labels)}
        lines.append(f"{indent}TRANSLATE")
        for i, label in enumerate(labels):
            comma = "," if i < len(labels) - 1 else ""
            lines.append(f"{indent}{indent}{key_of[label]} {_nexus_token(label)}{comma}")
        lines.append(f"{indent}{indent};")
    for i, tree in enumerate(items):
        name = tree.name if tree_names and tree.name else f"tree_{i + 1}"
        body = _write_body(tree, key_of if use_translate else None, newick_kw)
        prefix = ""
        if rooting:
            prefix = "[&R] " if tree.rooted else "[&U] "
        lines.append(f"{indent}TREE {_nexus_token(name)} = {prefix}{body};")
    lines.append("END;")
    lines.append("")
    return "\n".join(lines)


def _write_body(tree: Tree, key_of: dict[str, str] | None,
                newick_kw: dict[str, Any]) -> str:
    """Emit one tree specification with NEXUS quoting and TRANSLATE keys.

    Labels are quoted here rather than by the Newick writer because the two
    formats disagree: a backtick or a ``+`` is a perfectly good unquoted Newick
    label and NEXUS punctuation.  The names are substituted into a copy so the
    caller's tree is untouched, and the Newick writer is then told to leave them
    exactly as they are.
    """
    swapped = tree.copy()
    for node in preorder(swapped.root):
        if node.name:
            key = key_of.get(node.name) if key_of else None
            node.name = key if key is not None else _nexus_token(node.name)
    kw = dict(newick_kw)
    kw["quote_style"] = "never"
    kw["preserve_underscores"] = True
    return write_newick(swapped, terminator="", **kw)

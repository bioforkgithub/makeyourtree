# SPDX-License-Identifier: MIT
"""Source decoding and content-based format sniffing.

Never dispatch on the file extension.  ``.tre``, ``.tree``, ``.nwk``, ``.nex``,
``.t``, ``.trees`` and no extension at all are used interchangeably by the
programs that write these files -- BEAST writes NEXUS into ``.trees``, RAxML
writes Newick into files with no extension -- so the extension carries no
information.  Everything here looks at the bytes.

Decoding follows the same rule: sniff the byte-order mark, fall back to UTF-8,
and fall back again to latin-1, which cannot fail and preserves the byte values
for a later re-encode.  A file the user cannot open at all is a worse outcome
than a mojibake label.
"""

from __future__ import annotations

import gzip
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["FormatInfo", "detect_format", "read_source", "PROBE_BYTES"]

PROBE_BYTES = 8192
"""How much of a file is enough to recognise it.  Bounded on purpose: a BEAST
posterior sample is gigabytes, and sniffing must not read all of it."""

_UTF8_BOM = b"\xef\xbb\xbf"
_GZIP_MAGIC = b"\x1f\x8b"


@dataclass(slots=True)
class FormatInfo:
    """What :func:`detect_format` concluded about a piece of input.

    ``confidence`` is 1.0 for a magic-number match (``#NEXUS``, an XML root
    element) and lower for structural guesses.  ``n_trees`` counts tree
    definitions found in the text passed, so it is a lower bound when the caller
    only handed over a probe; ``notes`` records that and every other
    reservation, and is what the import dialog shows the user.
    """

    format: str
    confidence: float = 0.0
    n_trees: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_known(self) -> bool:
        return self.format != "unknown"


# --------------------------------------------------------------------- input


def _decode(data: bytes) -> str:
    """Bytes to text: BOM first, then UTF-8, then latin-1 as the last resort."""
    if data[:2] == _GZIP_MAGIC:
        # A gzipped tree file handed over with a .nwk name is common enough that
        # transparently decompressing beats a UnicodeDecodeError.
        try:
            data = gzip.decompress(data)
        except OSError:
            pass
    if data[:3] == _UTF8_BOM:
        return data[3:].decode("utf-8", errors="replace")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _looks_like_path(s: str) -> bool:
    """Cheap guard before touching the filesystem with a possible tree string."""
    if not s or len(s) > 4096 or "\n" in s or "\r" in s or "\x00" in s:
        return False
    if s.lstrip()[:1] in ("(", "#", "<", "["):
        return False
    try:
        return os.path.isfile(s)
    except (OSError, ValueError):
        return False


def read_source(source: Any) -> tuple[str, str | None]:
    """Normalise *source* to ``(text, origin)``.

    *source* may be a :class:`~pathlib.Path`, a filesystem path as a string, an
    open text or binary file object, a string holding the file contents, or
    bytes.  ``origin`` is the path the text came from, or ``None`` when the
    caller supplied content directly -- callers record where a tree came from
    without having to care which of those forms was passed.

    Line endings are normalised to a single newline: the NEXUS standard requires
    CR, LF and CRLF to be treated alike, and every other format here inherits
    that requirement.
    """
    origin: str | None = None
    if isinstance(source, Path):
        origin = str(source)
        text = _decode(source.read_bytes())
    elif isinstance(source, (bytes, bytearray, memoryview)):
        text = _decode(bytes(source))
    elif isinstance(source, str):
        if _looks_like_path(source):
            origin = source
            with open(source, "rb") as fh:
                text = _decode(fh.read())
        else:
            text = source
    elif hasattr(source, "read"):
        raw = source.read()
        text = _decode(raw) if isinstance(raw, (bytes, bytearray)) else str(raw)
        name = getattr(source, "name", None)
        if isinstance(name, str) and not name.startswith("<"):
            origin = name
    else:
        raise TypeError(f"cannot read a tree from {type(source).__name__}")
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, origin


# ------------------------------------------------------------------ sniffing


_XML_ROOT = re.compile(r"<\s*(?:[\w.-]+:)?([\w.-]+)")
_PHYLIP_HEAD = re.compile(r"^[ \t]*\d+[ \t]+\d+[ \t]*$")
_NEXUS_TREE_CMD = re.compile(r"(?im)(?:^|;)\s*u?tree\b")
_BEGIN_BLOCK = re.compile(r"(?i)^\s*begin\s+[\w']+\s*;")
_SQ = "'"


def _skip_trivia(text: str, limit: int) -> int:
    """Index of the first character that is neither whitespace nor a comment.

    A Newick file may open with ``[&R]`` and a sloppy NEXUS file may open with a
    comment before its ``#NEXUS`` header, so both have to be stepped over before
    the magic test runs.
    """
    i = 0
    n = min(len(text), limit)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "[":
            depth = 1
            i += 1
            while i < n and depth:
                if text[i] == "[":
                    depth += 1
                elif text[i] == "]":
                    depth -= 1
                i += 1
        else:
            break
    return i


def _count_newick_trees(text: str) -> int:
    """Semicolons at parenthesis depth 0, outside quotes and comments.

    Splitting a multi-tree file on a plain ``;`` corrupts any tree carrying one
    inside a quoted label, so the count respects the same lexical states the
    parser does.
    """
    n = 0
    depth = 0
    i = 0
    end = len(text)
    pending = False
    while i < end:
        c = text[i]
        if c == _SQ:
            i += 1
            while i < end:
                if text[i] == _SQ:
                    if i + 1 < end and text[i + 1] == _SQ:
                        i += 2
                        continue
                    break
                i += 1
        elif c == "[":
            d = 1
            i += 1
            while i < end and d:
                if text[i] == "[":
                    d += 1
                elif text[i] == "]":
                    d -= 1
                i += 1
            continue
        elif c == "(":
            depth += 1
            pending = True
        elif c == ")":
            depth -= 1
        elif c == ";":
            if depth == 0:
                n += 1
                pending = False
        elif not c.isspace():
            pending = True
        i += 1
    if pending and depth == 0:
        n += 1  # a final tree whose ';' was lost to a killed run
    return n


def detect_format(probe: Any) -> FormatInfo:
    """Recognise the tree format of *probe* from its content.

    Tests run in a fixed order because the formats overlap: a NEXUS file
    *contains* Newick strings, and a Newick file may legally start with the
    NEXUS command comment ``[&R]``, so the ``#NEXUS`` magic has to be tried
    before any structural Newick test.
    """
    text = probe if isinstance(probe, str) else read_source(probe)[0]
    notes: list[str] = []
    head = text[:PROBE_BYTES]
    body = head[_skip_trivia(head, PROBE_BYTES):]
    if not body.strip():
        return FormatInfo("unknown", 0.0, 0, ["input is empty or only comments"])

    if body.startswith("<"):
        m = _XML_ROOT.search(body)
        root = m.group(1).lower() if m else ""
        if root == "phyloxml" or "<phylogeny" in head or ":phylogeny" in head:
            if "phyloxml.org" not in head:
                notes.append("phyloXML namespace missing; matched on element names")
            return FormatInfo("phyloxml", 1.0 if root == "phyloxml" else 0.7,
                              text.count("<phylogeny") + text.count(":phylogeny"),
                              notes)
        if root == "nexml":
            return FormatInfo("unknown", 0.9, 0, ["NeXML is not supported"])
        return FormatInfo("unknown", 0.5, 0,
                          [f"XML root element {root!r} is not a tree format"])

    if body[:6].lower() == "#nexus":
        return FormatInfo("nexus", 1.0, len(_NEXUS_TREE_CMD.findall(text)), notes)
    if _BEGIN_BLOCK.match(body):
        notes.append("#NEXUS header missing; recognised by the BEGIN block")
        return FormatInfo("nexus", 0.6, len(_NEXUS_TREE_CMD.findall(text)), notes)

    if body[:1] == ">":
        return FormatInfo("unknown", 0.9, 0, ["looks like FASTA, not a tree"])
    if _PHYLIP_HEAD.match(body.split("\n", 1)[0]):
        return FormatInfo("unknown", 0.7, 0, ["looks like a PHYLIP alignment header"])

    n_trees = _count_newick_trees(text)
    if "[&&NHX" in head or "[&&nhx" in head:
        return FormatInfo("nhx", 0.95, n_trees, notes)
    if body[:1] == "(":
        if n_trees == 0:
            notes.append("no ';' at parenthesis depth 0")
        return FormatInfo("newick", 0.9 if n_trees else 0.6, max(n_trees, 1), notes)
    if ";" in body and "(" not in body.split(";", 1)[0]:
        notes.append("single-node tree")
        return FormatInfo("newick", 0.4, n_trees, notes)
    if text.count("(") == text.count(")") and text.rstrip().endswith(";"):
        notes.append("guessed Newick: parentheses balance and the text ends in ';'")
        return FormatInfo("newick", 0.3, max(n_trees, 1), notes)
    return FormatInfo("unknown", 0.0, 0, ["no format signature matched"])

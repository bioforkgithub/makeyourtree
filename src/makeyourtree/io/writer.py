# SPDX-License-Identifier: MIT
"""One entry point for writing a tree to any supported format.

The per-format writers stay independent -- they know nothing about files -- and
this module is the only place that decides where bytes go.  That keeps the
writers usable for string round trips, which is what the tests and the project
file layer need.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from ..core.errors import FormatError
from ..core.tree import Tree
from .newick import write_newick
from .nexus import write_nexus
from .phyloxml import write_phyloxml

__all__ = ["save_tree", "save_trees", "write_tree", "FORMATS"]

FORMATS: tuple[str, ...] = ("newick", "nhx", "nexus", "phyloxml")
"""Formats :func:`save_tree` can write.  ``nhx`` is Newick with annotations on."""


def write_tree(trees: Tree | Iterable[Tree], *, format: str = "newick",
               **kw: Any) -> str:
    """Serialise one or more trees to a string in *format*.

    ``newick`` writes only the first tree of a sequence per call, so multi-tree
    Newick output is a join of single-tree strings; NEXUS and phyloXML are
    natively multi-tree and take the whole sequence.
    """
    fmt = format.lower()
    if fmt in ("newick", "nwk", "nhx"):
        if fmt == "nhx":
            kw.setdefault("attrs", True)
        items = [trees] if isinstance(trees, Tree) else list(trees)
        return "\n".join(write_newick(t, **kw) for t in items) + "\n"
    if fmt in ("nexus", "nex"):
        return write_nexus(trees, **kw)
    if fmt in ("phyloxml", "xml"):
        return write_phyloxml(trees, **kw)
    raise FormatError(f"cannot write tree format {format!r}")


def save_tree(tree: Tree, dst: Any, *, format: str = "newick", **kw: Any) -> None:
    """Write *tree* to *dst*, which may be a path or an open file object.

    A text file object is written to directly; a binary one is handed UTF-8, so
    a caller that opened a file in either mode gets what it expects.
    """
    text = write_tree(tree, format=format, **kw)
    if isinstance(dst, (str, os.PathLike, Path)):
        Path(dst).write_text(text, encoding="utf-8", newline="\n")
        return
    if hasattr(dst, "write"):
        mode = getattr(dst, "mode", "")
        if "b" in mode:
            dst.write(text.encode("utf-8"))
        else:
            dst.write(text)
        return
    raise TypeError(f"cannot write a tree to {type(dst).__name__}")


def save_trees(trees: Iterable[Tree], dst: Any, *, format: str = "newick",
               **kw: Any) -> None:
    """Write several trees at once; see :func:`save_tree` for *dst*."""
    text = write_tree(list(trees), format=format, **kw)
    if isinstance(dst, (str, os.PathLike, Path)):
        Path(dst).write_text(text, encoding="utf-8", newline="\n")
        return
    if hasattr(dst, "write"):
        mode = getattr(dst, "mode", "")
        if "b" in mode:
            dst.write(text.encode("utf-8"))
        else:
            dst.write(text)
        return
    raise TypeError(f"cannot write a tree to {type(dst).__name__}")

# SPDX-License-Identifier: MIT
"""Exception hierarchy shared by every MakeYourTree core module."""

from __future__ import annotations


class MakeYourTreeError(Exception):
    """Base class for all errors raised by the MakeYourTree core."""


class ParseError(MakeYourTreeError):
    """A tree or annotation file could not be parsed.

    Carries the source position so callers can point a user at the offending
    character rather than at the whole file.
    """

    def __init__(self, message: str, *, line: int | None = None,
                 col: int | None = None, offset: int | None = None,
                 context: str | None = None) -> None:
        self.line = line
        self.col = col
        self.offset = offset
        self.context = context
        where = ""
        if line is not None:
            where = f" at line {line}" + (f", column {col}" if col is not None else "")
        elif offset is not None:
            where = f" at offset {offset}"
        super().__init__(f"{message}{where}" + (f"\n  {context}" if context else ""))


class FormatError(MakeYourTreeError):
    """The file format could not be determined, or is unsupported for this operation."""


class OperationError(MakeYourTreeError):
    """A tree edit was requested that would leave the tree in an invalid state."""


class TrackDataError(MakeYourTreeError):
    """Annotation data does not satisfy the requirements of the requested track type."""


class RenderError(MakeYourTreeError):
    """A scene could not be rendered by the selected backend."""

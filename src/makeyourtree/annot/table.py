# SPDX-License-Identifier: MIT
"""The MakeYourTree annotation table: an original, human-writable format.

Design note on provenance
-------------------------
This format is our own design.  It is a sectioned INI-style document because
that is the most legible plain-text container for "a bit of configuration plus
a table", it is trivially diffable in version control, and users can write it by
hand in any editor.  It deliberately does **not** reuse another product's
directive vocabulary; keyword names here are ours and describe our own option
model (see :mod:`makeyourtree.tracks`).

Grammar
-------
::

    file        := header? section*
    header      := "#makeyourtree-annotation" WS version NEWLINE
    section     := "[" name "]" NEWLINE line*
    line        := comment | blank | entry
    comment     := WS* ("#" | ";") ...
    entry       := key WS* "=" WS* value          (in keyed sections)
                 | field (SEP field)*             (in the [data] section)

Sections, all optional except ``[data]``:

``[track]``
    ``type``   the registered :attr:`~makeyourtree.tracks.base.Track.type_id`
    ``title``  display title
    ``id``     stable id, generated when absent
    ``match``  ``leaves`` (default) or ``all`` -- whether internal node names
               are eligible for matching

``[options]``
    Any key from the track type's option schema.  Values are parsed as JSON
    when they look like JSON, otherwise kept as strings.  Dotted keys nest:
    ``border.width = 0.5`` becomes ``{"border": {"width": 0.5}}``.

``[columns]``
    ``names = A, B, C`` names the data columns.  Absent means the columns are
    ``value``, ``value2``, ... and, when the first data line looks like a
    header, that line is used instead.

``[colors]``
    ``category = #rrggbb`` fixes the colour of a categorical value.  Values not
    listed are assigned from the theme palette in first-seen order.

``[legend]``
    ``title``, ``show`` (bool), ``order`` (comma-separated category order).

``[data]``
    One record per line: a node key, then one field per column.  The separator
    is detected once from the first data line -- tab if present, else comma,
    else runs of two or more spaces.  Fields may be quoted with ``"`` to
    contain the separator.  A field that is empty or ``-`` means "no value",
    which tracks render as a gap rather than as zero.

Everything is case-insensitive except node keys, category names and colours.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..style.color import Color

__all__ = ["AnnotationTable", "MAGIC", "EXTENSION", "PROJECT_EXTENSION"]

MAGIC = "#makeyourtree-annotation"
EXTENSION = ".mytrack"
PROJECT_EXTENSION = ".mytree"


@dataclass(slots=True)
class AnnotationTable:
    """Parsed contents of a ``.mytrack`` file, before it is bound to a tree."""

    track_type: str = ""
    title: str = ""
    track_id: str = ""
    match: str = "leaves"
    """``leaves`` or ``all``."""

    columns: list[str] = field(default_factory=list)
    records: dict[str, list[Any]] = field(default_factory=dict)
    """Node key -> one value per column, in file order."""

    options: dict[str, Any] = field(default_factory=dict)
    colors: dict[str, Color] = field(default_factory=dict)
    legend: dict[str, Any] = field(default_factory=dict)

    source: str | None = None
    version: int = 1

    def column_index(self, name: str) -> int:
        try:
            return self.columns.index(name)
        except ValueError:
            return -1

    def __len__(self) -> int:
        return len(self.records)

    def __repr__(self) -> str:
        return (f"<AnnotationTable {self.track_type!r} {self.title!r} "
                f"cols={len(self.columns)} rows={len(self.records)}>")

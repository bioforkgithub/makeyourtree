# SPDX-License-Identifier: MIT
"""Non-fatal problem reporting.

MakeYourTree parsers are deliberately lenient: real-world tree files are full of
small violations, and refusing to open a file is almost never the behaviour a
user wants.  Instead of raising, a parser records a :class:`Diagnostic` in a
:class:`DiagnosticSink` and carries on.  The application surfaces the sink as a
warning banner; the CLI prints it to stderr.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Severity(enum.IntEnum):
    INFO = 10
    WARNING = 20
    ERROR = 30

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One recoverable problem found while reading a file."""

    severity: Severity
    code: str
    """Stable machine-readable identifier, e.g. ``newick.missing-semicolon``."""
    message: str
    line: int | None = None
    col: int | None = None
    context: str | None = None

    def format(self) -> str:
        where = ""
        if self.line is not None:
            where = f" (line {self.line}" + (f", col {self.col}" if self.col is not None else "") + ")"
        return f"{self.severity}: [{self.code}] {self.message}{where}"


@dataclass(slots=True)
class DiagnosticSink:
    """Collects diagnostics; never raises."""

    items: list[Diagnostic] = field(default_factory=list)
    max_items: int = 1000
    _suppressed: int = 0

    def add(self, severity: Severity, code: str, message: str, *,
            line: int | None = None, col: int | None = None,
            context: str | None = None) -> None:
        if len(self.items) >= self.max_items:
            self._suppressed += 1
            return
        self.items.append(Diagnostic(severity, code, message, line, col, context))

    def info(self, code: str, message: str, **kw) -> None:
        self.add(Severity.INFO, code, message, **kw)

    def warn(self, code: str, message: str, **kw) -> None:
        self.add(Severity.WARNING, code, message, **kw)

    def error(self, code: str, message: str, **kw) -> None:
        self.add(Severity.ERROR, code, message, **kw)

    @property
    def suppressed(self) -> int:
        return self._suppressed

    @property
    def has_errors(self) -> bool:
        return any(d.severity >= Severity.ERROR for d in self.items)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self.items:
            out[str(d.severity)] = out.get(str(d.severity), 0) + 1
        return out

    def extend(self, other: "DiagnosticSink") -> None:
        for d in other.items:
            if len(self.items) >= self.max_items:
                self._suppressed += 1
            else:
                self.items.append(d)

    def format(self) -> str:
        lines = [d.format() for d in self.items]
        if self._suppressed:
            lines.append(f"... and {self._suppressed} further diagnostics (suppressed)")
        return "\n".join(lines)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

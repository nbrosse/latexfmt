"""Post-format sanity checks on the produced ``.tex`` files, and log scanning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .texutil import opaque_mask, read_text

_LONE_OP = re.compile(r"^\s*[=+\-]\s*$")
_TRAILING_WS = re.compile(r"[ \t]+$")
_DANGLING_AMP = re.compile(r"&\s*$")


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    kind: str
    text: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.kind}: {self.text.strip()[:80]}"


def check_file(path: Path, columns: int, encoding: str = "utf-8") -> list[Finding]:
    """Check one formatted file. Opaque bodies are exempt from every check:
    the pipeline deliberately leaves them byte-for-byte alone."""
    findings: list[Finding] = []
    lines = read_text(path, encoding).split("\n")
    mask = opaque_mask(lines)
    for i, line in enumerate(lines, 1):
        if mask[i - 1]:
            continue
        if "\t" in line:
            findings.append(Finding(path, i, "tab", line))
        if _TRAILING_WS.search(line):
            findings.append(Finding(path, i, "trailing-whitespace", line))
        if _LONE_OP.match(line):
            findings.append(Finding(path, i, "lone-operator", line))
        if _DANGLING_AMP.search(line):
            findings.append(Finding(path, i, "dangling-&", line))
        if len(line) > columns:
            findings.append(Finding(path, i, f">{columns}-cols", line))
    return findings


def check_files(paths: list[Path], columns: int,
                encoding: str = "utf-8") -> list[Finding]:
    findings: list[Finding] = []
    for p in paths:
        findings.extend(check_file(p, columns, encoding))
    return findings


# ---------------------------------------------------------------------------
# Build-log scanning
# ---------------------------------------------------------------------------
# TeX hard-wraps the log at max_print_line (79 by default), so a warning can be
# split mid-sentence. Rejoin before matching, or "... undefined" is missed.
_LOG_WIDTH = 79

_REF_UNDEFINED = re.compile(
    r"Warning:\s*(?:Hyper r|R)eference\s*[`'\"][^'\"]*['\"]?\s*[^\n]*?undefined",
    re.IGNORECASE)
_MULTIPLY_DEFINED = re.compile(
    r"Warning:\s*Label\s*[`'\"][^'\"]*['\"]?\s*[^\n]*?multiply[- ]defined",
    re.IGNORECASE)
_CITE_UNDEFINED = re.compile(
    r"Warning:\s*Citation\s*[`'\"][^'\"]*['\"]?\s*[^\n]*?undefined",
    re.IGNORECASE)
_SUMMARY_REFS = re.compile(r"There were undefined references", re.IGNORECASE)
_SUMMARY_LABELS = re.compile(r"There were multiply-defined labels", re.IGNORECASE)
_PAGES = re.compile(r"Output written on .*?\((\d+) page")
_OVERFULL = re.compile(r"Overfull \\hbox")


@dataclass(frozen=True)
class BuildLog:
    """What a ``latexmk`` run reported. ``pages`` is None if undeterminable."""

    undefined_refs: int = 0
    multiply_defined: int = 0
    undefined_citations: int = 0
    pages: int | None = None
    overfull: int = 0

    @property
    def label_problems(self) -> int:
        """Problems that pruning a ``\\label`` could have caused.

        Undefined *citations* are excluded: they come from the bibliography and
        are never latexfmt's doing.
        """
        return self.undefined_refs + self.multiply_defined


def unwrap_log(text: str, width: int = _LOG_WIDTH) -> str:
    """Undo TeX's hard wrap: a line of exactly ``width`` chars is continued."""
    out: list[str] = []
    buf = ""
    for line in text.split("\n"):
        buf += line
        if len(line) < width:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return "\n".join(out)


def scan_build_log(log_path: Path) -> BuildLog:
    """Summarize a LaTeX ``.log``.

    Matches the specific ``LaTeX Warning:`` forms rather than the bare words
    "undefined"/"multiply defined", which also occur in font-shape warnings,
    package chatter and file paths.
    """
    if not log_path.is_file():
        return BuildLog()
    text = unwrap_log(log_path.read_text(encoding="utf-8", errors="replace"))
    refs = len(_REF_UNDEFINED.findall(text))
    multi = len(_MULTIPLY_DEFINED.findall(text))
    # The end-of-run summary is authoritative: if it fired but no individual
    # warning matched, still report one problem rather than a false all-clear.
    if not refs and _SUMMARY_REFS.search(text):
        refs = 1
    if not multi and _SUMMARY_LABELS.search(text):
        multi = 1
    pages = [int(m) for m in _PAGES.findall(text)]
    return BuildLog(
        undefined_refs=refs,
        multiply_defined=multi,
        undefined_citations=len(_CITE_UNDEFINED.findall(text)),
        pages=pages[-1] if pages else None,
        overfull=len(_OVERFULL.findall(text)),
    )

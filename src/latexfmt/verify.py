"""Post-format sanity checks on the produced ``.tex`` files."""

from __future__ import annotations

import re
from pathlib import Path

from .texutil import BEGIN_RE, END_RE, OPAQUE

_LONE_OP = re.compile(r"^\s*[=+\-]\s*$")
_TRAILING_WS = re.compile(r"[ \t]+$")
_DANGLING_AMP = re.compile(r"&\s*$")


class Finding:
    def __init__(self, file: Path, line: int, kind: str, text: str):
        self.file = file
        self.line = line
        self.kind = kind
        self.text = text

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.kind}: {self.text.strip()[:80]}"


def _opaque_mask(lines: list[str]) -> list[bool]:
    """Per-line flag: True where the line sits inside an opaque environment."""
    mask = [False] * len(lines)
    depth = 0
    for i, line in enumerate(lines):
        s = line.strip()
        opening = bool(BEGIN_RE.match(s) and BEGIN_RE.match(s).group(1) in OPAQUE)
        closing = bool(END_RE.match(s) and END_RE.match(s).group(1) in OPAQUE)
        if closing and depth > 0:
            depth -= 1
            mask[i] = True
            continue
        mask[i] = depth > 0
        if opening:
            depth += 1
    return mask


def check_file(path: Path, columns: int) -> list[Finding]:
    findings: list[Finding] = []
    lines = path.read_text(encoding="utf-8").split("\n")
    mask = _opaque_mask(lines)
    for i, line in enumerate(lines, 1):
        if "\t" in line:
            findings.append(Finding(path, i, "tab", line))
        if _TRAILING_WS.search(line):
            findings.append(Finding(path, i, "trailing-whitespace", line))
        if _LONE_OP.match(line):
            findings.append(Finding(path, i, "lone-operator", line))
        inside_opaque = mask[i - 1]
        if not inside_opaque and _DANGLING_AMP.search(line):
            findings.append(Finding(path, i, "dangling-&", line))
        if not inside_opaque and len(line) > columns:
            findings.append(Finding(path, i, f">{columns}-cols", line))
    return findings


def check_files(paths: list[Path], columns: int) -> list[Finding]:
    findings: list[Finding] = []
    for p in paths:
        findings.extend(check_file(p, columns))
    return findings


def scan_build_log(log_path: Path) -> tuple[int, int | None, int]:
    """Return (undefined_or_multiply_defined_count, page_count, overfull_count).

    ``page_count`` is None if it cannot be determined from the log.
    """
    if not log_path.is_file():
        return (0, None, 0)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    bad = len(re.findall(r"undefined|multiply.defined", text, re.IGNORECASE))
    overfull = len(re.findall(r"Overfull \\hbox", text))
    pages = None
    m = re.findall(r"Output written on .*?\((\d+) page", text)
    if m:
        pages = int(m[-1])
    return (bad, pages, overfull)

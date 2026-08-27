"""Shared LaTeX parsing helpers: regexes, environment classes, brace/env-depth
utilities, project input resolution, autonum detection and reference scanning.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

BEGIN_RE = re.compile(r"\\begin\{([^}]*)\}")
END_RE = re.compile(r"\\end\{([^}]*)\}")
LABEL_RE = re.compile(r"\\label\{([^}]*)\}")

# Environments whose interior must never be reflowed/re-indented by us.
OPAQUE = {
    "tikzpicture", "verbatim", "lstlisting", "comment", "minted",
    "tabular", "tabular*", "tabularx", "longtable", "supertabular", "tabbing",
}
# Top-level display-math environments we normalize.
MATH = {"equation", "equation*", "align", "align*"}
# Nested math constructs that may contain their own '\\' and '&'; ignored when
# deciding whether a display is genuinely multi-line.
NESTED_MATH = {
    "bmatrix", "pmatrix", "matrix", "vmatrix", "Vmatrix", "Bmatrix",
    "smallmatrix", "cases", "aligned", "array", "split", "gathered", "subarray",
}

# Commands that reference a label (cleveref, hyperref). Used to decide which
# \label{...} are dead. Conservative: references inside comments count too, so
# nothing referenced anywhere is dropped.
_REF_NAMES = [
    "ref", "eqref", "pageref", "autoref", "nameref", "vref", "Vref",
    "vpageref", "cref", "Cref", "cpageref", "Cpageref", "crefrange",
    "Crefrange", "cpagerefrange", "labelcref", "labelcpageref", "subref",
]
_REF_RE = re.compile(r"\\(?:" + "|".join(_REF_NAMES) + r")\*?\s*\{([^}]*)\}")
_HYPERREF_RE = re.compile(r"\\hyperref\s*\[([^\]]*)\]")
_INPUT_RE = re.compile(r"\\(?:input|include|subfile)\{([^}]*)\}")


def split_comment(line: str) -> tuple[str, str]:
    """Split ``line`` at its first unescaped ``%`` into (code, comment).

    ``comment`` includes the ``%`` and is ``""`` when the line has none.
    """
    i = 0
    while i < len(line):
        if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
            return line[:i], line[i:]
        i += 1
    return line, ""


def strip_comment(line: str) -> str:
    """Drop an unescaped ``%...`` comment (keep escaped ``\\%``)."""
    return split_comment(line)[0]


def sub_outside_comments(rx: re.Pattern, repl, text: str) -> str:
    """``rx.sub(repl, ...)`` applied to the code part of every line only.

    Comments are passed through untouched, so a commented-out ``\\label`` is
    never rewritten or counted.
    """
    out = []
    for line in text.split("\n"):
        code, comment = split_comment(line)
        out.append(rx.sub(repl, code) + comment)
    return "\n".join(out)


def findall_outside_comments(rx: re.Pattern, text: str) -> list:
    """``rx.findall`` over the code part of every line only."""
    found: list = []
    for line in text.split("\n"):
        found.extend(rx.findall(split_comment(line)[0]))
    return found


def _skip_comment(s: str, i: int) -> int:
    """Index of the newline ending the comment starting at ``s[i]`` (or len)."""
    nl = s.find("\n", i)
    return len(s) if nl < 0 else nl


def has_unescaped_percent(s: str) -> bool:
    i = 0
    while i < len(s):
        if s[i] == "%" and (i == 0 or s[i - 1] != "\\"):
            return True
        i += 1
    return False


def end_outside_comment(line: str, env: str) -> tuple[str, str] | None:
    """Match ``\\end{env}`` outside a comment; return (before, after) or None.

    Scanning the code part only keeps a commented-out ``\\end{...}`` from
    truncating a block.
    """
    code, comment = split_comment(line)
    m = re.match(r"^(.*)\\end\{" + re.escape(env) + r"\}(.*)$", code)
    if not m:
        return None
    return m.group(1), m.group(2) + comment


def top_level_has_linebreak(body: str) -> bool:
    """True if ``body`` contains a ``\\\\`` at brace- and nested-env-depth 0
    (ignoring ``\\\\[`` spacing rows)."""
    braced = envd = i = 0
    s = body
    n = len(s)
    while i < n:
        m = BEGIN_RE.match(s, i)
        if m and m.group(1) in NESTED_MATH:
            envd += 1
            i = m.end()
            continue
        m = END_RE.match(s, i)
        if m and m.group(1) in NESTED_MATH:
            envd -= 1
            i = m.end()
            continue
        c = s[i]
        if c == "%" and (i == 0 or s[i - 1] != "\\"):
            i = _skip_comment(s, i)  # a \\ inside a comment is not a row break
            continue
        if c == "\\" and i + 1 < n and s[i + 1] == "\\":
            nxt = s[i + 2] if i + 2 < n else ""
            if braced == 0 and envd == 0 and nxt != "[":
                return True
            i += 2
            continue
        if c == "{" and (i == 0 or s[i - 1] != "\\"):
            braced += 1
        elif c == "}" and (i == 0 or s[i - 1] != "\\"):
            braced -= 1
        i += 1
    return False


def strip_toplevel_amp(body: str) -> str:
    """Remove alignment ``&`` at brace/nested-env depth 0 (single-line case)."""
    braced = envd = i = 0
    out: list[str] = []
    s = body
    n = len(s)
    while i < n:
        m = BEGIN_RE.match(s, i)
        if m and m.group(1) in NESTED_MATH:
            envd += 1
            out.append(m.group(0))
            i = m.end()
            continue
        m = END_RE.match(s, i)
        if m and m.group(1) in NESTED_MATH:
            envd -= 1
            out.append(m.group(0))
            i = m.end()
            continue
        c = s[i]
        if c == "%" and (i == 0 or s[i - 1] != "\\"):
            end = _skip_comment(s, i)  # copy the comment through untouched
            out.append(s[i:end])
            i = end
            continue
        if c == "&" and braced == 0 and envd == 0 and (i == 0 or s[i - 1] != "\\"):
            i += 1
            continue
        if c == "{" and (i == 0 or s[i - 1] != "\\"):
            braced += 1
        elif c == "}" and (i == 0 or s[i - 1] != "\\"):
            braced -= 1
        out.append(c)
        i += 1
    return "".join(out)


class Project:
    """Resolved view of a LaTeX project rooted at ``root``.

    - ``all_files``: root + every resolved input (for reference scanning).
    - ``body_files``: inputs pulled in *after* ``\\begin{document}``.
    - ``preamble_files``: inputs pulled in *before* ``\\begin{document}``.
    """

    def __init__(self, root: Path):
        self.root = root
        self.all_files: list[Path] = []
        self.body_files: list[Path] = []
        self.preamble_files: list[Path] = []


def _resolve_path(name: str, base: Path) -> Path | None:
    p = base / name
    if p.suffix != ".tex":
        p = p.with_suffix(".tex")
    return p if p.is_file() else None


def _excluded(path: Path, exclude: list[str]) -> bool:
    s = str(path)
    return any(fnmatch.fnmatch(s, pat) or fnmatch.fnmatch(path.name, pat)
               for pat in exclude)


def resolve_project(root_path: str | Path,
                    exclude: list[str] | None = None) -> Project:
    """Resolve a root ``.tex`` and all files it ``\\input``s / ``\\include``s.

    Inputs are classified preamble vs body by their position relative to
    ``\\begin{document}`` in the root. Nested inputs inherit their parent's
    class. Files matching ``exclude`` globs are skipped.
    """
    exclude = exclude or []
    root = Path(root_path).resolve()
    proj = Project(root)
    seen: set[Path] = set()

    def walk(path: Path, cls: str) -> None:
        if path in seen or not path.is_file():
            return
        seen.add(path)
        proj.all_files.append(path)
        text = path.read_text(encoding="utf-8")
        segments = [(text, cls)]
        if path == root:
            idx = text.find(r"\begin{document}")
            if idx >= 0:
                segments = [(text[:idx], "preamble"), (text[idx:], "body")]
        for seg_text, seg_cls in segments:
            for m in _INPUT_RE.finditer(seg_text):
                child = _resolve_path(m.group(1), path.parent)
                if child is None or _excluded(child, exclude):
                    continue
                if child not in seen:
                    (proj.preamble_files if seg_cls == "preamble"
                     else proj.body_files).append(child)
                walk(child, seg_cls)

    walk(root, "body")
    return proj


def detect_autonum(files: list[Path]) -> bool:
    """True if any file loads the ``autonum`` package."""
    pat = re.compile(r"\\(?:usepackage|RequirePackage)\b[^\n]*\{[^}]*\bautonum\b")
    return any(pat.search(f.read_text(encoding="utf-8")) for f in files)


def collect_referenced_labels(files: list[Path]) -> set[str]:
    """All label names referenced anywhere (cleveref comma-lists expanded)."""
    refs: set[str] = set()
    for f in files:
        text = f.read_text(encoding="utf-8")
        for rx in (_REF_RE, _HYPERREF_RE):
            for m in rx.finditer(text):
                arg = m.group(1).strip()
                if arg:
                    refs.add(arg)  # whole arg: single-label cmds (\eqref{a(y,s)})
                for name in arg.split(","):  # cleveref comma-lists
                    name = name.strip()
                    if name:
                        refs.add(name)
    return refs

"""Standardize display-math bodies (equation/align).

For every top-level equation/align block (not inside an opaque env), reflow the
body:
  * split into rows at top-level ``\\\\`` (ignoring ``\\\\`` inside braces /
    nested matrix/cases/substack/... constructs and ``\\\\[`` spacing rows);
  * within each row, treat existing physical lines as atomic, safe chunks;
  * resplit chunks so every spaced binary operator leads its piece, merge a
    dangling alignment ``&`` onto the following relation, collapse double
    spaces;
  * greedily pack pieces to a column target, breaking only *before* a piece
    that starts with a binary operator / relation / spacing macro (AMS style);
  * fall back to a hard break if a single piece already exceeds the width;
  * reserve room for the ``\\\\`` row separator on non-final rows.

Body lines are emitted at (begin-indent + 2); latexindent normalizes afterward.
The begin line (with any leading ``\\label``) and the ``\\end`` line are kept.
"""

from __future__ import annotations

import re

from .texutil import (
    BEGIN_RE,
    END_RE,
    NESTED_MATH,
    OPAQUE,
    end_outside_comment,
    has_unescaped_percent,
)

BLOCK_BEGIN_RE = re.compile(r"^(\s*)\\begin\{(equation|align)\}(.*)$")

OP_CHAR = set("=+-<>")
OP_MACRO = {
    "pm", "mp", "cdot", "times", "div", "ast", "star", "circ", "bullet",
    "oplus", "ominus", "otimes", "odot", "wedge", "vee", "cup", "cap",
    "setminus", "sqcup", "sqcap", "uplus",
    "leq", "geq", "leqslant", "geqslant", "le", "ge", "ll", "gg", "neq", "ne",
    "equiv", "sim", "simeq", "approx", "cong", "propto", "asymp", "doteq",
    "subset", "subseteq", "supset", "supseteq", "sqsubseteq", "sqsupseteq",
    "in", "ni", "notin", "prec", "succ", "preceq", "succeq",
    "to", "mapsto", "rightarrow", "longrightarrow", "Rightarrow",
    "Longrightarrow", "leftarrow", "Leftarrow", "leftrightarrow", "iff",
    "implies", "hookrightarrow",
    "quad", "qquad",
}


def _starts_with_op(ch: str) -> bool:
    if not ch:
        return False
    if ch[0] in OP_CHAR:
        return True
    m = re.match(r"\\([a-zA-Z]+)", ch)
    return bool(m) and m.group(1) in OP_MACRO


def _op_at(s: str, i: int) -> int:
    """Length of an operator token starting at ``s[i]`` (0 if none). '&' excl."""
    c = s[i]
    if c in "=+-<>":
        return 1
    if c == "\\":
        m = re.match(r"\\([a-zA-Z]+)", s[i:])
        if m and m.group(1) in OP_MACRO:
            return m.end()
    return 0


def _resplit_operators(chunk: str) -> list[str]:
    """Split a chunk at top-level spaces preceding a binary operator so the
    operator leads its piece (AMS). Never splits inside braces / nested math or
    across a comment; ``&`` does not trigger a split."""
    pieces: list[str] = []
    braced = envd = i = 0
    buf = ""
    s = chunk
    n = len(s)
    while i < n:
        mb = BEGIN_RE.match(s, i)
        if mb and mb.group(1) in NESTED_MATH:
            envd += 1
            buf += mb.group(0)
            i = mb.end()
            continue
        me = END_RE.match(s, i)
        if me and me.group(1) in NESTED_MATH:
            envd -= 1
            buf += me.group(0)
            i = me.end()
            continue
        c = s[i]
        if c == "%" and (i == 0 or s[i - 1] != "\\"):
            buf += s[i:]
            break
        if c == " " and braced == 0 and envd == 0:
            j = i + 1
            while j < n and s[j] == " ":
                j += 1
            if j < n and _op_at(s, j) and buf.strip():
                pieces.append(buf.strip())
                buf = ""
                i = j
                continue
        if c == "{" and (i == 0 or s[i - 1] != "\\"):
            braced += 1
        elif c == "}" and (i == 0 or s[i - 1] != "\\"):
            braced -= 1
        buf += c
        i += 1
    if buf.strip():
        pieces.append(buf.strip())
    return pieces


def _merge_trailing_amp(chunks: list[str]) -> list[str]:
    """Attach a dangling alignment tab ``&`` at a piece's end to the next piece
    so align rows read ``LHS &= RHS`` uniformly (never a lone trailing ``&``)."""
    out: list[str] = []
    i = 0
    while i < len(chunks):
        c = chunks[i].rstrip()
        if c.endswith("&") and i + 1 < len(chunks):
            base = c[:-1].rstrip()
            if base:
                out.append(base)
            chunks[i + 1] = "&" + chunks[i + 1].lstrip()
        else:
            out.append(chunks[i])
        i += 1
    return out


def _split_rows(body_lines: list[str]) -> list[list[str]]:
    """Split body physical lines into rows of atomic chunks at top-level ``\\\\``."""
    rows: list[list[str]] = []
    cur: list[str] = []
    braced = envd = 0
    for raw in body_lines:
        line = raw.strip()
        if line == "":
            continue
        buf = ""
        i = 0
        s = line
        n = len(s)
        while i < n:
            mb = BEGIN_RE.match(s, i)
            if mb and mb.group(1) in NESTED_MATH:
                envd += 1
                buf += mb.group(0)
                i = mb.end()
                continue
            me = END_RE.match(s, i)
            if me and me.group(1) in NESTED_MATH:
                envd -= 1
                buf += me.group(0)
                i = me.end()
                continue
            c = s[i]
            if c == "%" and (i == 0 or s[i - 1] != "\\"):
                buf += s[i:]
                i = n
                break
            if c == "\\" and i + 1 < n and s[i + 1] == "\\":
                nxt = s[i + 2] if i + 2 < n else ""
                if braced == 0 and envd == 0 and nxt != "[":
                    if buf.strip():
                        cur.append(buf.strip())
                    rows.append(cur)
                    cur = []
                    buf = ""
                    i += 2
                    continue
                buf += "\\\\"
                i += 2
                continue
            if c == "{" and (i == 0 or s[i - 1] != "\\"):
                braced += 1
            elif c == "}" and (i == 0 or s[i - 1] != "\\"):
                braced -= 1
            buf += c
            i += 1
        if buf.strip():
            cur.append(buf.strip())
    rows.append(cur)
    while rows and not rows[-1]:
        rows.pop()
    return rows


def _wrap_row(chunks: list[str], indent: int, width: int, reserve: int = 0) -> list[str]:
    pad = " " * indent
    avail = max(20, width - indent - reserve)
    flat: list[str] = []
    for ch in chunks:
        flat.extend(_resplit_operators(ch))
    flat = _merge_trailing_amp(flat)
    chunks = [re.sub(r" {2,}", " ", c) for c in flat]
    n = len(chunks)
    allow = [False] * n
    force = [has_unescaped_percent(c) for c in chunks]
    for k in range(1, n):
        if _starts_with_op(chunks[k]):
            allow[k] = True
    out: list[str] = []
    start = 0
    while start < n:
        end = start
        length = 0
        while end < n:
            add = len(chunks[end]) + (1 if end > start else 0)
            if length + add <= avail or end == start:
                length += add
                end += 1
                if force[end - 1]:  # comment: nothing may follow on this line
                    break
            else:
                break
        if end >= n:
            out.append(pad + " ".join(chunks[start:end]))
            break
        brk = None
        for k in range(end, start, -1):
            if allow[k]:
                brk = k
                break
        if brk is None:
            brk = end if end > start else start + 1
        out.append(pad + " ".join(chunks[start:brk]))
        start = brk
    return out


def standardize(lines: list[str], width: int = 100) -> list[str]:
    """Reflow every top-level equation/align body to ``width`` columns."""
    out: list[str] = []
    i = 0
    n = len(lines)
    opaque: list[str] = []
    while i < n:
        line = lines[i]
        s = line.strip()
        if opaque:
            out.append(line)
            _update_opaque(opaque, s)
            i += 1
            continue
        mb_op = BEGIN_RE.match(s)
        if mb_op and mb_op.group(1) in OPAQUE:
            out.append(line)
            _update_opaque(opaque, s)
            i += 1
            continue
        m = BLOCK_BEGIN_RE.match(line)
        if m:
            indent, env, rest = m.group(1), m.group(2), m.group(3)
            begin_line = indent + "\\begin{" + env + "}"
            while True:
                lm = re.match(r"^\s*(\\label\{[^}]*\})(.*)$", rest)
                if lm:
                    begin_line += lm.group(1)
                    rest = lm.group(2)
                else:
                    break
            body_lines: list[str] = []
            if rest.strip():
                body_lines.append(rest.strip())
            j = i + 1
            tail = ""
            while j < n:
                em = end_outside_comment(lines[j], env)
                if em:
                    if em[0].strip():
                        body_lines.append(em[0])
                    tail = em[1]
                    break
                body_lines.append(lines[j])
                j += 1
            body_indent = len(indent) + 2
            rows = _split_rows(body_lines)
            out.append(begin_line)
            last_idx = max((k for k, r in enumerate(rows) if r), default=-1)
            for r_idx, row in enumerate(rows):
                if not row:
                    continue
                last_row = r_idx == last_idx
                wl = _wrap_row(row, body_indent, width, reserve=0 if last_row else 3)
                for li, ln in enumerate(wl):
                    if li == len(wl) - 1 and not last_row:
                        if has_unescaped_percent(ln):
                            # \\ appended after a comment would be commented out
                            out.append(ln)
                            out.append(" " * body_indent + "\\\\")
                        else:
                            out.append(ln + " \\\\")
                    else:
                        out.append(ln)
            end_line = indent + "\\end{" + env + "}"
            if tail.strip():
                end_line += tail
            out.append(end_line)
            i = j + 1
            continue
        out.append(line)
        i += 1
    return out


def _update_opaque(stack: list[str], s: str) -> None:
    i = 0
    while i < len(s):
        mb = BEGIN_RE.match(s, i)
        if mb:
            if mb.group(1) in OPAQUE:
                stack.append(mb.group(1))
            i = mb.end()
            continue
        me = END_RE.match(s, i)
        if me:
            if stack and stack[-1] == me.group(1):
                stack.pop()
            i = me.end()
            continue
        i += 1

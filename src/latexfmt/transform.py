"""Per-file transformation passes (generalized from the session ``clean_tex``).

Order (see :func:`transform_text`):
  1. whitespace  2. math-env convert (+ prune math labels)  3. indentation
  4. prose reflow (Rewrap-style)  5. math-body standardize  6. collapse blanks

All passes operate on a list of lines and return a new list.
"""

from __future__ import annotations

import re

from . import mathstd
from .texutil import (
    BEGIN_RE,
    END_RE,
    LABEL_RE,
    MATH,
    OPAQUE,
    has_unescaped_percent,
    strip_comment,
    strip_toplevel_amp,
    top_level_has_linebreak,
)

# Line-initial control sequences that begin structural / non-prose lines.
STRUCT_PREFIX = (
    "\\begin", "\\end", "\\[", "\\]", "\\item", "\\section", "\\subsection",
    "\\subsubsection", "\\paragraph", "\\part", "\\input", "\\include",
    "\\bibliography", "\\label", "\\vspace", "\\hspace", "\\centering",
    "\\appendix", "\\maketitle", "\\acks", "\\renewcommand", "\\newcommand",
    "\\providecommand", "\\def", "\\let", "\\usepackage", "\\RequirePackage",
    "\\documentclass", "\\newpage", "\\clearpage", "\\doparttoc",
    "\\faketableofcontents", "\\parttoc", "\\title", "\\author", "\\editor",
    "\\ShortHeadings", "\\firstpageno", "\\name", "\\addr", "\\AND",
    "\\noalign", "\\small", "\\footnotesize", "\\scriptsize", "\\normalsize",
    "\\large", "\\Large", "\\LARGE", "\\setlength", "\\setcounter",
    "\\raggedright", "\\raggedleft", "\\toprule", "\\midrule", "\\bottomrule",
    "\\cmidrule", "\\hline", "\\rowcolor", "\\multicolumn", "\\captionsetup",
    "\\qedhere", "\\nonumber", "\\notag", "\\arraystretch", "\\tabcolsep",
    "\\newtheorem", "\\newaliascnt", "\\aliascntresetthe", "\\crefname",
    "\\Crefname", "\\makeatletter", "\\makeatother", "\\newenvironment",
    "\\DeclareMathOperator", "\\definecolor", "\\tikzset", "\\pgfplotsset",
    "\\newcolumntype", "\\newlength",
)
# Control sequences that may legitimately *start* a prose line (and thus keep
# it reflowable). Inline math ``\(`` is handled separately.
ALLOWED_TEXT_STARTERS = {
    "cref", "Cref", "crefrange", "Crefrange", "eqref", "ref", "autoref",
    "pageref", "nameref", "vref", "Vref",
    "citep", "citet", "cite", "citealp", "citealt", "citeauthor", "citeyear",
    "textit", "textbf", "emph", "text", "mbox", "textsc", "textrm", "texttt",
    "textsf", "underline", "footnote", "textcolor",
}

BEGIN_MATH_RE = re.compile(r"^(\s*)\\begin\{(equation\*?|align\*?)\}(.*)$")


# ---------------------------------------------------------------------------
# Pass 1: whitespace
# ---------------------------------------------------------------------------
def pass_whitespace(lines: list[str]) -> list[str]:
    return [ln.replace("\t", " ").rstrip() for ln in lines]


# ---------------------------------------------------------------------------
# Pass 2: math-environment conversion + label pruning (math blocks only)
# ---------------------------------------------------------------------------
def _target_env(orig: str, multiline: bool, autonum: bool) -> str:
    numbered = not orig.endswith("*") and orig != "["
    if autonum:  # stars are undefined under autonum -> always unstarred
        return "align" if multiline else "equation"
    if multiline:
        return "align" if numbered else "align*"
    return "equation" if numbered else "equation*"


def pass_convert(lines: list[str], autonum: bool, refs: set[str],
                 prune: bool) -> tuple[list[str], list[str]]:
    """Normalize display-math environments and (if ``prune``) drop unreferenced
    labels *within those math blocks only*. Returns (lines, removed_labels)."""
    out: list[str] = []
    removed: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        mb = BEGIN_MATH_RE.match(line)
        db = re.match(r"^(\s*)\\\[\s*(.*)$", line)
        if mb:
            indent, env, rest = mb.group(1), mb.group(2), mb.group(3)
            block = [strip_comment(rest)]
            j = i + 1
            tail = ""
            while j < n:
                em = re.match(r"^(.*)\\end\{" + re.escape(env) + r"\}(.*)$", lines[j])
                if em:
                    block.append(strip_comment(em.group(1)))
                    tail = em.group(2)
                    break
                block.append(strip_comment(lines[j]))
                j += 1
            body = "\n".join(block)
            multiline = top_level_has_linebreak(body)
            target = _target_env(env, multiline, autonum)
            out.extend(_emit_block(indent, target, body, multiline, refs, prune,
                                   removed))
            if tail.strip():
                out.append(indent + tail.strip())
            i = j + 1
            continue
        if db is not None and line.strip() == "\\[":
            indent = db.group(1)
            block = []
            j = i + 1
            while j < n and lines[j].strip() != "\\]":
                block.append(strip_comment(lines[j]))
                j += 1
            body = "\n".join(block)
            multiline = top_level_has_linebreak(body)
            target = _target_env("[", multiline, autonum)
            out.extend(_emit_block(indent, target, body, multiline, refs, prune,
                                   removed))
            i = j + 1
            continue
        out.append(line)
        i += 1
    return out, removed


def _emit_block(indent: str, target: str, body: str, multiline: bool,
                refs: set[str], prune: bool, removed: list[str]) -> list[str]:
    def drop(m: re.Match) -> str:
        name = m.group(1)
        if not prune or name in refs:
            return m.group(0)
        removed.append(name)
        return ""

    out = [indent + "\\begin{" + target + "}"]
    if multiline:
        for bl in LABEL_RE.sub(drop, body).split("\n"):
            bl = bl.strip()
            if bl:
                out.append(indent + "  " + bl)
    else:
        kept: list[str] = []
        for lb in LABEL_RE.findall(body):
            if not prune or lb in refs:
                kept.append(lb)
            else:
                removed.append(lb)
        body_nolabel = strip_toplevel_amp(LABEL_RE.sub("", body))
        if kept:
            out[0] += "".join("\\label{%s}" % lb for lb in kept)
        for bl in body_nolabel.split("\n"):
            bl = bl.strip()
            if bl:
                out.append(indent + "  " + bl)
    out.append(indent + "\\end{" + target + "}")
    return out


# ---------------------------------------------------------------------------
# Pass 4: indentation
# ---------------------------------------------------------------------------
def _increment(name: str, indent: int) -> int:
    return 0 if name == "proof" else indent


def pass_indent(lines: list[str], indent: int) -> list[str]:
    out: list[str] = []
    stack: list[dict] = []

    def body_indent() -> int:
        return stack[-1]["indent"] if stack else 0

    def top_kind() -> str | None:
        return stack[-1]["kind"] if stack else None

    for line in lines:
        s = line.strip()
        if s == "":
            out.append("")
            continue
        if top_kind() in ("opaque", "math"):
            name = stack[-1]["name"]
            if re.match(r"^\s*\\end\{" + re.escape(name) + r"\}", line):
                stack.pop()
                out.append(" " * body_indent() + s)
            elif top_kind() == "opaque":
                out.append(line)  # untouched interior
            else:
                out.append(" " * stack[-1]["indent"] + s)
            continue
        mend = re.match(r"^\\end\{([^}]*)\}", s)
        if mend:
            if stack and stack[-1]["name"] == mend.group(1):
                stack.pop()
            cur = body_indent()
            out.append(" " * cur + s)
            _update_stack(stack, s[mend.end():], indent)
            continue
        cur = body_indent()
        out.append(" " * cur + s)
        _update_stack(stack, s, indent)
    return out


def _update_stack(stack: list[dict], s: str, indent: int) -> None:
    i = 0
    while i < len(s):
        mb = BEGIN_RE.match(s, i)
        if mb:
            name = mb.group(1)
            base = stack[-1]["indent"] if stack else 0
            kind = ("opaque" if name in OPAQUE
                    else "math" if name in MATH else "normal")
            stack.append({"name": name, "indent": base + _increment(name, indent),
                          "kind": kind})
            i = mb.end()
            if kind in ("opaque", "math"):
                return
            continue
        me = END_RE.match(s, i)
        if me:
            if stack and stack[-1]["name"] == me.group(1):
                stack.pop()
            i = me.end()
            continue
        i += 1


# ---------------------------------------------------------------------------
# Pass 5: prose reflow (Rewrap-style)
# ---------------------------------------------------------------------------
def is_structural(s: str, wrap_comments: bool) -> bool:
    if s == "":
        return True
    if "\\begin{" in s or "\\end{" in s:
        return True
    if not wrap_comments and has_unescaped_percent(s):
        return True
    if s in ("\\[", "\\]"):
        return True
    if s[0] in "{}":
        return True
    if s.startswith(STRUCT_PREFIX):
        return True
    if s[0] == "\\":
        if s.startswith("\\(") or s.startswith("\\$"):
            return False
        m = re.match(r"\\([a-zA-Z@]+)", s)
        token = m.group(1) if m else ""
        return token not in ALLOWED_TEXT_STARTERS
    return False


def _wrap(text: str, width: int, indent: int) -> list[str]:
    pad = " " * indent
    words = [w for w in text.split(" ") if w != ""]
    if not words:
        return []
    lines = [pad + words[0]]
    for w in words[1:]:
        if len(lines[-1]) + 1 + len(w) <= width:
            lines[-1] += " " + w
        else:
            lines.append(pad + w)
    return lines


def pass_reflow(lines: list[str], columns: int, wrap_comments: bool,
                indent: int) -> list[str]:
    out: list[str] = []
    stack: list[dict] = []
    para: list[str] = []
    para_indent = [0]

    def flush() -> None:
        if not para:
            return
        text = re.sub(r"\s+", " ", " ".join(p.strip() for p in para)).strip()
        out.extend(_wrap(text, columns, para_indent[0]))
        para.clear()

    for line in lines:
        s = line.strip()
        kind = stack[-1]["kind"] if stack else "normal"
        if kind in ("math", "opaque"):
            flush()
            out.append(line)
            m = re.match(r"^\\end\{([^}]*)\}", s)
            if m and stack and stack[-1]["name"] == m.group(1):
                stack.pop()
            continue
        if is_structural(s, wrap_comments):
            flush()
            out.append(line)
            _update_stack(stack, s, indent)
            continue
        # Reflowable prose: wrap indent comes from the line's actual leading
        # whitespace (already set by pass_indent), so it is correct for any step.
        lead = len(line) - len(line.lstrip(" "))
        if para and lead != para_indent[0]:
            flush()
        if not para:
            para_indent[0] = lead
        para.append(s)
    flush()
    return out


# ---------------------------------------------------------------------------
# Pass 7: collapse blank lines
# ---------------------------------------------------------------------------
def pass_blanks(lines: list[str]) -> list[str]:
    out: list[str] = []
    prev_blank = False
    for ln in lines:
        blank = ln.strip() == ""
        if blank and prev_blank:
            continue
        out.append(ln)
        prev_blank = blank
    while out and out[0].strip() == "":
        out.pop(0)
    while out and out[-1].strip() == "":
        out.pop()
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def transform_text(
    text: str,
    *,
    refs: set[str],
    autonum: bool,
    columns: int = 100,
    indent: int = 2,
    wrap_comments: bool = False,
    prune_labels: bool = True,
    minimal: bool = False,
) -> tuple[str, list[str]]:
    """Apply the passes to one file's ``text``. Returns (new_text, removed_labels).

    ``minimal`` restricts the work to whitespace + blank-line normalization
    (used for preamble/macro-definition files, whose structure must not be
    touched)."""
    lines = text.split("\n")
    lines = pass_whitespace(lines)
    if minimal:
        lines = pass_blanks(lines)
        result = "\n".join(lines)
        if not result.endswith("\n"):
            result += "\n"
        return result, []
    lines, removed = pass_convert(lines, autonum, refs, prune_labels)
    lines = pass_indent(lines, indent)
    lines = pass_reflow(lines, columns, wrap_comments, indent)
    lines = mathstd.standardize(lines, columns)
    lines = pass_blanks(lines)
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result, removed

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
    LatexfmtError,
    end_outside_comment,
    findall_outside_comments,
    has_unescaped_percent,
    opaque_mask,
    strip_toplevel_amp,
    sub_outside_comments,
    top_level_row_count,
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
    """Tabs -> spaces, strip trailing whitespace -- outside opaque environments.

    Opaque bodies (tabular, verbatim, tikzpicture, ...) are hand-aligned and
    every later pass leaves them alone; normalizing their whitespace here would
    silently reflow tables that the pipeline promises to keep verbatim.
    """
    return [ln if inside else ln.replace("\t", " ").rstrip()
            for ln, inside in zip(lines, opaque_mask(lines), strict=True)]


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
    opaque = opaque_mask(lines)
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if opaque[i]:  # e.g. an align shown inside a verbatim example
            out.append(line)
            i += 1
            continue
        mb = BEGIN_MATH_RE.match(line)
        db = re.match(r"^(\s*)\\\[\s*(.*)$", line)
        if mb:
            indent, env, rest = mb.group(1), mb.group(2), mb.group(3)
            same_line_end = end_outside_comment(rest, env)
            if same_line_end:
                block = [same_line_end[0]]
                tail = same_line_end[1]
                j = i
            else:
                block = [rest]
                j = i + 1
                tail = ""
                while j < n:
                    em = end_outside_comment(lines[j], env)
                    if em:
                        block.append(em[0])
                        tail = em[1]
                        break
                    block.append(lines[j])
                    j += 1
                if j >= n:
                    raise LatexfmtError(f"unterminated \\begin{{{env}}}")
            body = "\n".join(block)
            multiline = top_level_row_count(body) > 1
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
                block.append(lines[j])
                j += 1
            if j >= n:
                raise LatexfmtError("unterminated \\[")
            body = "\n".join(block)
            multiline = top_level_row_count(body) > 1
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
        body = sub_outside_comments(LABEL_RE, drop, body)
    else:
        kept: list[str] = []
        for lb in findall_outside_comments(LABEL_RE, body):
            if not prune or lb in refs:
                kept.append(lb)
            else:
                removed.append(lb)
        # A single-line display carries its label on the \begin line; alignment
        # tabs are meaningless once the row is not split.
        body = strip_toplevel_amp(sub_outside_comments(LABEL_RE, "", body))
        if kept:
            out[0] += "".join(f"\\label{{{lb}}}" for lb in kept)
    for bl in body.split("\n"):
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
    # Only full-line comments are safe to reflow. Moving text after a trailing
    # comment can turn it into live LaTeX on continuation lines.
    if has_unescaped_percent(s) and (not wrap_comments or not s.startswith("%")):
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


def _wrap(text: str, width: int, indent: int, prefix: str = "") -> list[str]:
    pad = " " * indent
    words = [w for w in text.split(" ") if w != ""]
    if not words:
        return []
    lines = [pad + prefix + words[0]]
    for w in words[1:]:
        if len(lines[-1]) + 1 + len(w) <= width:
            lines[-1] += " " + w
        else:
            lines.append(pad + prefix + w)
    return lines


def pass_reflow(lines: list[str], columns: int, wrap_comments: bool,
                indent: int) -> list[str]:
    out: list[str] = []
    stack: list[dict] = []
    para: list[str] = []
    para_indent = [0]
    para_prefix = [""]

    def flush() -> None:
        if not para:
            return
        text = re.sub(r"\s+", " ", " ".join(p.strip() for p in para)).strip()
        out.extend(_wrap(text, columns, para_indent[0], para_prefix[0]))
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
        comment = re.match(r"^(%+\s?)(.*)$", s) if wrap_comments else None
        prefix = comment.group(1) if comment else ""
        content = comment.group(2) if comment else s
        # Reflowable prose: wrap indent comes from the line's actual leading
        # whitespace (already set by pass_indent), so it is correct for any step.
        lead = len(line) - len(line.lstrip(" "))
        if para and (lead != para_indent[0] or prefix != para_prefix[0]):
            flush()
        if not para:
            para_indent[0] = lead
            para_prefix[0] = prefix
        # Empty comment lines are paragraph boundaries and must remain comments.
        if comment and not content:
            flush()
            out.append(" " * lead + prefix.rstrip())
            continue
        para.append(content)
    flush()
    return out


# ---------------------------------------------------------------------------
# Pass 7: collapse blank lines
# ---------------------------------------------------------------------------
def pass_blanks(lines: list[str]) -> list[str]:
    out: list[str] = []
    prev_blank = False
    for ln, inside in zip(lines, opaque_mask(lines), strict=True):
        if inside:  # blank lines in a verbatim body are content
            out.append(ln)
            prev_blank = False
            continue
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


def _opaque_bodies(lines: list[str]) -> list[list[str]]:
    """The body of every opaque environment, in order, as runs of masked lines."""
    bodies: list[list[str]] = []
    prev = False
    for ln, inside in zip(lines, opaque_mask(lines), strict=True):
        if inside:
            if not prev:
                bodies.append([])
            bodies[-1].append(ln)
        prev = inside
    return bodies


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
    before = _opaque_bodies(lines)
    lines, removed = pass_convert(lines, autonum, refs, prune_labels)
    lines = pass_indent(lines, indent)
    lines = pass_reflow(lines, columns, wrap_comments, indent)
    lines = mathstd.standardize(lines, columns)
    lines = pass_blanks(lines)
    # A build cannot catch an altered verbatim example (it still compiles), so
    # the promise that opaque bodies are left alone is checked here, before
    # anything is written.
    if _opaque_bodies(lines) != before:
        raise LatexfmtError("internal error: an opaque environment (verbatim, "
                            "tabular, ...) would be modified; nothing was written")
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result, removed

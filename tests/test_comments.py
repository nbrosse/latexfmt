"""Comments inside display math must survive formatting (regression)."""

import pytest

from latexfmt.texutil import LatexfmtError
from latexfmt.transform import transform_text

REFS = {"eq:used"}


def fmt(text, **kw):
    kw.setdefault("refs", REFS)
    kw.setdefault("autonum", False)
    return transform_text(text, **kw)[0]


def test_full_line_comment_in_align_is_kept():
    out = fmt("\\begin{align}\n"
              "  % why this holds\n"
              "  a &= b \\\\\n"
              "  c &= d\n"
              "\\end{align}\n")
    assert "% why this holds" in out


def test_trailing_comment_in_equation_is_kept():
    out = fmt("\\begin{equation}\n"
              "  a = b % a remark\n"
              "\\end{equation}\n")
    assert "% a remark" in out


def test_row_separator_not_swallowed_by_trailing_comment():
    """A row ending in a comment must not get ``\\\\`` appended after it."""
    out = fmt("\\begin{align}\n"
              "  a &= b % remark\n"
              "  \\\\ c &= d\n"
              "\\end{align}\n")
    lines = [ln.strip() for ln in out.splitlines()]
    assert "% remark" in out
    assert not any(ln.startswith("%") and ln.endswith("\\\\") for ln in lines), out
    assert "\\\\" in out, out  # the separator survives on its own line


def test_linebreak_inside_comment_is_not_a_row_break():
    """A ``\\\\`` in a comment must not make a single-line display multi-line."""
    out = fmt("\\begin{align}\n"
              "  a &= b % beware of \\\\ here\n"
              "\\end{align}\n")
    assert "\\begin{equation}" in out, out


def test_commented_label_is_not_hoisted_or_pruned():
    out = fmt("\\begin{align}\n"
              "  a &= b % \\label{eq:dead}\n"
              "\\end{align}\n")
    assert "% \\label{eq:dead}" in out, out
    assert "\\begin{equation}\\label" not in out, out


def test_commented_end_does_not_truncate_the_block():
    out = fmt("\\begin{align}\n"
              "  a &= b % \\end{align} not really\n"
              "  \\\\ c &= d\n"
              "\\end{align}\n")
    # exactly one *real* \end{align}; the one inside the comment is preserved
    code = [ln.split("%")[0] for ln in out.splitlines()]
    assert sum(ln.count("\\end{align}") for ln in code) == 1, out
    assert "% \\end{align} not really" in out, out
    assert "c &= d" in out, out


def test_referenced_label_still_hoisted_and_dead_label_still_pruned():
    out, removed = transform_text(
        "\\begin{align}\n  a &= b \\label{eq:used} \\\\\n  c &= d \\label{eq:dead}\n"
        "\\end{align}\n",
        refs=REFS, autonum=False)
    assert "eq:dead" in removed
    assert "\\label{eq:used}" in out
    assert "\\label{eq:dead}" not in out


def test_wrapped_comments_keep_a_marker_on_every_line():
    out = fmt("% " + "word " * 20 + "\n", columns=20, wrap_comments=True)
    assert len(out.splitlines()) > 1
    assert all(line.startswith("% ") for line in out.splitlines())
    assert fmt(out, columns=20, wrap_comments=True) == out


def test_trailing_comment_is_not_reflowed_into_live_text():
    source = "Code. % " + "word " * 20 + "\nFollowing prose.\n"
    assert fmt(source, columns=20, wrap_comments=True).splitlines()[0] == \
        source.splitlines()[0].rstrip()


def test_same_line_math_environment_is_handled():
    out = fmt("\\begin{align} a &= b \\end{align} After.\n")
    assert out == ("\\begin{equation}\n  a = b\n\\end{equation}\nAfter.\n")
    assert fmt(out) == out


def test_unterminated_math_environment_is_rejected():
    with pytest.raises(LatexfmtError, match="unterminated"):
        fmt("\\begin{align}\n  a &= b\nAfter.\n")

"""Unit tests for the parsing helpers the passes are built on."""

from __future__ import annotations

from latexfmt.texutil import (
    LABEL_RE,
    collect_referenced_labels,
    detect_autonum,
    findall_outside_comments,
    opaque_mask,
    resolve_project,
    split_comment,
    strip_toplevel_amp,
    sub_outside_comments,
    top_level_row_count,
)


class TestSplitComment:
    def test_plain(self):
        assert split_comment("a % b") == ("a ", "% b")

    def test_escaped_percent_is_not_a_comment(self):
        assert split_comment(r"50\% off") == (r"50\% off", "")

    def test_no_comment(self):
        assert split_comment("a + b") == ("a + b", "")

    def test_comment_at_start(self):
        assert split_comment("% all of it") == ("", "% all of it")


class TestTopLevelRowCount:
    def test_single_row(self):
        assert top_level_row_count("a = b") == 1

    def test_two_rows(self):
        assert top_level_row_count(r"a &= b \\ c &= d") == 2

    def test_spacing_separator_counts(self):
        assert top_level_row_count(r"a &= b \\[2pt] c &= d") == 2

    def test_starred_separator_counts(self):
        assert top_level_row_count(r"a &= b \\* c &= d") == 2

    def test_trailing_separator_adds_no_row(self):
        assert top_level_row_count(r"a &= b \\") == 1
        assert top_level_row_count(r"a &= b \\[2pt]") == 1

    def test_break_inside_nested_env_is_not_top_level(self):
        assert top_level_row_count(
            r"M &= \begin{bmatrix} a \\ b \end{bmatrix}") == 1

    def test_break_inside_braces_is_not_top_level(self):
        assert top_level_row_count(r"a &= \substack{x \\ y}") == 1

    def test_break_inside_comment_is_not_a_row(self):
        assert top_level_row_count("a &= b % beware \\\\ here") == 1


class TestStripToplevelAmp:
    def test_removes_alignment_tab(self):
        assert strip_toplevel_amp("a &= b") == "a = b"

    def test_keeps_amp_in_nested_env(self):
        body = r"M = \begin{bmatrix} a & b \end{bmatrix}"
        assert strip_toplevel_amp(body) == body

    def test_keeps_escaped_amp(self):
        assert strip_toplevel_amp(r"a \& b") == r"a \& b"

    def test_keeps_amp_inside_a_comment(self):
        assert strip_toplevel_amp("a = b % keep & this") == "a = b % keep & this"


class TestCommentAwareRegex:
    def test_sub_skips_comments(self):
        out = sub_outside_comments(LABEL_RE, "", r"\label{a} % \label{b}")
        assert out == r" % \label{b}"

    def test_findall_skips_comments(self):
        assert findall_outside_comments(LABEL_RE, r"\label{a} % \label{b}") == ["a"]


class TestOpaqueMask:
    def test_body_masked_delimiters_not(self):
        lines = [r"\begin{tabular}{ll}", "a & b", r"\end{tabular}", "after"]
        assert opaque_mask(lines) == [False, True, False, False]

    def test_non_opaque_env_is_not_masked(self):
        lines = [r"\begin{align}", "a &= b", r"\end{align}"]
        assert opaque_mask(lines) == [False, False, False]


class TestProjectResolution:
    def _write(self, tmp_path, name, text):
        (tmp_path / name).write_text(text, encoding="utf-8")
        return tmp_path / name

    def test_classifies_preamble_and_body_inputs(self, tmp_path):
        self._write(tmp_path, "macros.tex", "\\newcommand{\\x}{y}\n")
        self._write(tmp_path, "chapter.tex", "text\n")
        root = self._write(tmp_path, "main.tex",
                           "\\input{macros}\n\\begin{document}\n"
                           "\\input{chapter}\n\\end{document}\n")
        proj = resolve_project(root)
        assert [p.name for p in proj.preamble_files] == ["macros.tex"]
        assert [p.name for p in proj.body_files] == ["chapter.tex"]
        assert len(proj.all_files) == 3

    def test_exclude_globs_are_honoured(self, tmp_path):
        self._write(tmp_path, "old_draft.tex", "x\n")
        root = self._write(tmp_path, "main.tex",
                           "\\begin{document}\n\\input{old_draft}\n\\end{document}\n")
        proj = resolve_project(root, exclude=["*old*"])
        assert proj.body_files == []

    def test_missing_input_is_skipped_not_fatal(self, tmp_path):
        root = self._write(tmp_path, "main.tex",
                           "\\begin{document}\n\\input{gone}\n\\end{document}\n")
        assert resolve_project(root).body_files == []

    def test_input_cycle_terminates(self, tmp_path):
        self._write(tmp_path, "a.tex", "\\input{b}\n")
        self._write(tmp_path, "b.tex", "\\input{a}\n")
        root = self._write(tmp_path, "main.tex",
                           "\\begin{document}\n\\input{a}\n\\end{document}\n")
        assert len(resolve_project(root).all_files) == 3

    def test_detect_autonum(self, tmp_path):
        plain = self._write(tmp_path, "p.tex", "\\usepackage{amsmath}\n")
        auto = self._write(tmp_path, "a.tex", "\\usepackage{autonum}\n")
        assert not detect_autonum([plain])
        assert detect_autonum([plain, auto])


class TestReferenceCollection:
    def test_cleveref_comma_list_is_expanded(self, tmp_path):
        f = tmp_path / "a.tex"
        f.write_text(r"\cref{eq:a,eq:b}", encoding="utf-8")
        refs = collect_referenced_labels([f])
        assert {"eq:a", "eq:b"} <= refs

    def test_label_containing_a_comma_is_kept_whole(self, tmp_path):
        f = tmp_path / "a.tex"
        f.write_text(r"\eqref{a(y,s)}", encoding="utf-8")
        assert "a(y,s)" in collect_referenced_labels([f])

    def test_hyperref_bracket_form(self, tmp_path):
        f = tmp_path / "a.tex"
        f.write_text(r"\hyperref[sec:x]{link}", encoding="utf-8")
        assert "sec:x" in collect_referenced_labels([f])

    def test_reference_inside_a_comment_still_counts(self, tmp_path):
        """Deliberately conservative: a commented-out \\ref keeps its label
        alive rather than risking a silent deletion."""
        f = tmp_path / "a.tex"
        f.write_text(r"% \ref{eq:x}", encoding="utf-8")
        assert "eq:x" in collect_referenced_labels([f])

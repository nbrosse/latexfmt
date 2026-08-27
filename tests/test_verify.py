"""Post-format checks and build-log scanning."""

from __future__ import annotations

from latexfmt.verify import check_file, scan_build_log, unwrap_log


class TestCheckFile:
    def _f(self, tmp_path, text):
        p = tmp_path / "f.tex"
        p.write_text(text, encoding="utf-8")
        return p

    def test_clean_file_has_no_findings(self, tmp_path):
        assert check_file(self._f(tmp_path, "a = b\n"), 100) == []

    def test_flags_tab_trailing_and_long_line(self, tmp_path):
        p = self._f(tmp_path, "a\tb\nc   \n" + "x" * 120 + "\n")
        kinds = {f.kind for f in check_file(p, 100)}
        assert {"tab", "trailing-whitespace", ">100-cols"} <= kinds

    def test_flags_lone_operator_and_dangling_amp(self, tmp_path):
        p = self._f(tmp_path, "  =\nfoo &\n")
        kinds = {f.kind for f in check_file(p, 100)}
        assert {"lone-operator", "dangling-&"} <= kinds

    def test_opaque_bodies_are_exempt(self, tmp_path):
        """Tabs and dangling & inside a tabular are the author's, not ours."""
        p = self._f(tmp_path,
                    "\\begin{tabular}{ll}\n\ta\t&\tb \\\\\n\\end{tabular}\n")
        assert check_file(p, 100) == []


class TestUnwrapLog:
    def test_rejoins_a_hard_wrapped_line(self):
        first, second = "x" * 79, "continued"
        assert unwrap_log(first + "\n" + second) == first + second

    def test_leaves_short_lines_alone(self):
        assert unwrap_log("short\nlines") == "short\nlines"


class TestScanBuildLog:
    def _log(self, tmp_path, text):
        p = tmp_path / "main.log"
        p.write_text(text, encoding="utf-8")
        return p

    def test_missing_log_is_empty(self, tmp_path):
        r = scan_build_log(tmp_path / "absent.log")
        assert r.label_problems == 0 and r.pages is None

    def test_undefined_reference(self, tmp_path):
        r = scan_build_log(self._log(tmp_path,
            "LaTeX Warning: Reference `eq:x' on page 1 undefined on input line 4.\n"))
        assert r.undefined_refs == 1
        assert r.label_problems == 1

    def test_multiply_defined_label(self, tmp_path):
        r = scan_build_log(self._log(tmp_path,
            "LaTeX Warning: Label `eq:x' multiply defined.\n"))
        assert r.multiply_defined == 1

    def test_undefined_citation_is_not_a_label_problem(self, tmp_path):
        """Citations come from the bibliography; label pruning cannot cause them."""
        r = scan_build_log(self._log(tmp_path,
            "LaTeX Warning: Citation `smith99' on page 1 undefined on input line 4.\n"))
        assert r.undefined_citations == 1
        assert r.label_problems == 0

    def test_font_warning_is_not_counted(self, tmp_path):
        """The old scanner matched the bare word 'undefined' anywhere."""
        r = scan_build_log(self._log(tmp_path,
            "LaTeX Font Warning: Font shape `OT1/cmr/m/it' undefined\n"
            "(Font)              using `OT1/cmr/m/n' instead on input line 9.\n"))
        assert r.label_problems == 0

    def test_undefined_in_a_path_is_not_counted(self, tmp_path):
        r = scan_build_log(self._log(tmp_path,
            "(/usr/share/texmf/tex/latex/undefined-helper.sty)\n"))
        assert r.label_problems == 0

    def test_hard_wrapped_warning_is_still_found(self, tmp_path):
        """TeX wraps the log at 79 columns, splitting warnings mid-sentence."""
        line = "LaTeX Warning: Reference `a-very-long-label-name-here' on page 12"
        head = line + "x" * (79 - len(line))
        r = scan_build_log(self._log(tmp_path, head + "\n undefined on input line 3.\n"))
        assert r.undefined_refs == 1

    def test_summary_line_alone_still_reports_a_problem(self, tmp_path):
        r = scan_build_log(self._log(tmp_path, "There were undefined references.\n"))
        assert r.undefined_refs == 1

    def test_no_double_count_of_warning_and_summary(self, tmp_path):
        """One broken \\ref is one problem, not two."""
        r = scan_build_log(self._log(tmp_path,
            "LaTeX Warning: Reference `eq:x' on page 1 undefined on input line 4.\n"
            "\nLaTeX Warning: There were undefined references.\n"))
        assert r.undefined_refs == 1

    def test_pages_and_overfull(self, tmp_path):
        r = scan_build_log(self._log(tmp_path,
            "Overfull \\hbox (5pt too wide) in paragraph at lines 1--2\n"
            "Output written on main.pdf (7 pages, 1234 bytes).\n"))
        assert r.pages == 7
        assert r.overfull == 1

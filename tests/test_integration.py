"""End-to-end tests against the real latexindent / latexmk finalizers.

Skipped unless both tools are on PATH. The rest of the suite is hermetic; this
is the only place the external toolchain is exercised.
"""

from __future__ import annotations

import shutil

import pytest

from latexfmt.cli import EXIT_FAILED, EXIT_OK, main

pytestmark = pytest.mark.skipif(
    not (shutil.which("latexindent") and shutil.which("latexmk")),
    reason="needs latexindent and latexmk on PATH")

MAIN = """\\documentclass{article}
\\usepackage{amsmath,amssymb,cleveref}
\\begin{document}
\\input{body}
\\end{document}
"""


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")

    def make(body):
        (tmp_path / "body.tex").write_text(body, encoding="utf-8")
        return tmp_path / "main.tex"

    make.body = tmp_path / "body.tex"  # type: ignore[attr-defined]
    return make


def test_formats_and_builds_cleanly(proj, capsys):
    root = proj(
        "\\section{S}\n"
        "\\begin{align}\n  a &= b + c \\label{eq:live}\n\\end{align}\n"
        "See \\cref{eq:live}.\n")
    assert main([str(root)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "verify: clean" in out
    assert "build: ok" in out
    assert "\\begin{equation}\\label{eq:live}" in proj.body.read_text()


def test_broken_reference_fails_the_build(proj, capsys):
    root = proj("Text.\n\nSee \\ref{eq:nope}.\n")
    assert main([str(root)]) == EXIT_FAILED
    assert "undefined-refs: 1" in capsys.readouterr().out


def test_bundled_config_keeps_output_verify_clean(proj, capsys):
    """Without a project .latexindent.yaml the fallback must still produce
    output that passes latexfmt's own checks (tabs, & padding, tabular)."""
    root = proj(
        "\\begin{align}\n  a &= b\n\\end{align}\n"
        "\\begin{tabular}{ll}\n\tx\t&\ty \\\\\n\\end{tabular}\n")
    assert main([str(root), "--no-build"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "bundled defaults" in out
    assert "verify: clean" in out


def test_hand_aligned_tabular_survives_the_full_pipeline(proj):
    body = "\\begin{tabular}{ll}\n\ta\t&\tb \\\\\n\tccc\t&\td \\\\\n\\end{tabular}\n"
    root = proj(body)
    assert main([str(root), "--no-build"]) == EXIT_OK
    assert proj.body.read_text() == body

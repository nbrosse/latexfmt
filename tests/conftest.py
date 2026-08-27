"""Shared fixtures: a minimal on-disk LaTeX project."""

from __future__ import annotations

import pathlib

import pytest

MAIN = """\\documentclass{article}
\\usepackage{amsmath}
\\begin{document}
\\input{body}
\\end{document}
"""


@pytest.fixture
def project(tmp_path: pathlib.Path):
    """Build a root+body project. Returns (root_path, write_body callable)."""
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")
    body = tmp_path / "body.tex"
    body.write_text("x\n", encoding="utf-8")

    def make(body_text: str) -> pathlib.Path:
        body.write_text(body_text, encoding="utf-8")
        return tmp_path / "main.tex"

    make.dir = tmp_path        # type: ignore[attr-defined]
    make.body = body           # type: ignore[attr-defined]
    return make

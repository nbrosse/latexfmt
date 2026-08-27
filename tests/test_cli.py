"""CLI behaviour: exit codes, preview modes, and file handling.

Every test passes --no-build --no-latexindent so the suite is hermetic: no
latexmk, no Perl latexindent, no TeX installation required.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import latexfmt.cli as cli
from latexfmt.cli import EXIT_FAILED, EXIT_OK, EXIT_USAGE, EXIT_WOULD_CHANGE, main
from latexfmt.config import Tools

HERMETIC = ["--no-build", "--no-latexindent"]

UNFORMATTED = "\\begin{align}\n  a &= b\n\\end{align}\n"
FORMATTED = "\\begin{equation}\n  a = b\n\\end{equation}\n"


def run(root, *extra):
    return main([str(root), *HERMETIC, *extra])


def test_reformats_and_exits_ok(project):
    root = project(UNFORMATTED)
    assert run(root) == EXIT_OK
    assert project.body.read_text() == FORMATTED


def test_check_exits_1_when_reformatting_is_needed(project, capsys):
    root = project(UNFORMATTED)
    assert run(root, "--check") == EXIT_WOULD_CHANGE
    assert project.body.read_text() == UNFORMATTED, "--check must not write"
    assert "would change: 1" in capsys.readouterr().out


def test_check_exits_0_when_already_formatted(project):
    root = project(FORMATTED)
    assert run(root, "--check") == EXIT_OK


def test_dry_run_prints_a_diff_and_writes_nothing(project, capsys):
    root = project(UNFORMATTED)
    assert run(root, "--dry-run") == EXIT_WOULD_CHANGE
    out = capsys.readouterr().out
    assert "--- " in out and "+++ " in out
    assert "+\\begin{equation}" in out
    assert project.body.read_text() == UNFORMATTED


def test_missing_root_exits_usage(tmp_path, capsys):
    assert main([str(tmp_path / "nope.tex"), *HERMETIC]) == EXIT_USAGE
    assert "root file not found" in capsys.readouterr().err


def test_undecodable_file_reports_instead_of_crashing(project, capsys):
    root = project(UNFORMATTED)
    project.body.write_bytes(b"\\section{caf\xe9}\n")  # latin-1, not utf-8
    assert run(root) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "not valid utf-8" in err
    assert "--encoding" in err


def test_explicit_encoding_round_trips(project):
    root = project(UNFORMATTED)
    project.body.write_bytes("\\section{café}\n".encode("latin-1"))
    assert run(root, "--encoding", "latin-1") == EXIT_OK
    assert project.body.read_text(encoding="latin-1") == "\\section{café}\n"


def test_backup_writes_orig(project):
    root = project(UNFORMATTED)
    assert run(root, "--backup") == EXIT_OK
    assert (project.dir / "body.tex.orig").read_text() == UNFORMATTED


def test_keep_labels_disables_pruning(project):
    root = project("\\begin{align}\n  a &= b \\label{eq:dead}\n\\end{align}\n")
    assert run(root, "--keep-labels") == EXIT_OK
    assert "eq:dead" in project.body.read_text()


def test_dead_label_is_pruned_by_default(project, capsys):
    root = project("\\begin{align}\n  a &= b \\label{eq:dead}\n\\end{align}\n")
    assert run(root) == EXIT_OK
    assert "eq:dead" not in project.body.read_text()
    assert "labels removed" in capsys.readouterr().out


def test_referenced_label_survives(project):
    root = project("\\begin{align}\n  a &= b \\label{eq:live}\n\\end{align}\n"
                   "See \\cref{eq:live}.\n")
    assert run(root) == EXIT_OK
    assert "eq:live" in project.body.read_text()


def test_preamble_untouched_without_all(project):
    """Without --all only body files are formatted; the root keeps its preamble."""
    root = project(UNFORMATTED)
    before = root.read_text()
    assert run(root) == EXIT_OK
    assert root.read_text() == before


@pytest.mark.parametrize("flag", ["--check", "--dry-run"])
def test_preview_modes_never_write(project, flag):
    root = project(UNFORMATTED)
    assert run(root, flag) == EXIT_WOULD_CHANGE
    assert project.body.read_text() == UNFORMATTED


def test_failed_build_restores_original_sources(project, monkeypatch, capsys):
    root = project(UNFORMATTED)
    monkeypatch.setattr(cli, "detect_tools",
                        lambda: Tools(latexindent=None, latexmk="latexmk"))
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda *a, **kw: SimpleNamespace(returncode=1))
    assert main([str(root), "--no-latexindent"]) == EXIT_FAILED
    assert project.body.read_text() == UNFORMATTED
    assert "restored 1 source file" in capsys.readouterr().out


def test_transform_error_does_not_partially_write_project(tmp_path, capsys):
    root = tmp_path / "main.tex"
    first = tmp_path / "first.tex"
    second = tmp_path / "second.tex"
    root.write_text("\\begin{document}\n\\input{first}\n\\input{second}\n"
                    "\\end{document}\n")
    first.write_text(UNFORMATTED)
    second.write_text("\\begin{align}\na &= b\n")
    assert main([str(root), *HERMETIC]) == EXIT_USAGE
    assert first.read_text() == UNFORMATTED
    assert "unterminated" in capsys.readouterr().err


def test_missing_explicit_config_is_reported(project, tmp_path, capsys):
    root = project(FORMATTED)
    assert run(root, "--config", str(tmp_path / "missing.toml")) == EXIT_USAGE
    assert "config file not found" in capsys.readouterr().err


def test_invalid_config_type_is_reported_without_traceback(project, tmp_path, capsys):
    root = project(FORMATTED)
    config = tmp_path / "bad.toml"
    config.write_text('columns = "wide"\n')
    assert run(root, "--config", str(config)) == EXIT_USAGE
    assert "columns must be a positive integer" in capsys.readouterr().err

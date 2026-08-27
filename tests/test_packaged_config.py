"""The bundled latexindent config must not drift from the repo-root copy."""

from pathlib import Path

from latexfmt.config import packaged_latexindent_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bundled_config_exists_and_is_readable():
    p = packaged_latexindent_config()
    assert p.is_file(), p
    assert "defaultIndent" in p.read_text(encoding="utf-8")


def test_bundled_config_matches_repo_root_example():
    """README tells users to copy the root .latexindent.yaml into their project;
    it must stay identical to the one latexfmt falls back to."""
    root = REPO_ROOT / ".latexindent.yaml"
    assert root.read_text(encoding="utf-8") == \
        packaged_latexindent_config().read_text(encoding="utf-8")

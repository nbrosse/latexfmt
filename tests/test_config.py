"""Config discovery, parsing, and CLI precedence."""

from __future__ import annotations

import pytest

from latexfmt.cli import _merge, build_parser
from latexfmt.config import Config, find_config, load_config, validate_config
from latexfmt.texutil import LatexfmtError


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


class TestDiscovery:
    def test_finds_latexfmt_toml_in_start_dir(self, tmp_path):
        cfg = write(tmp_path / "latexfmt.toml", "columns = 80\n")
        assert find_config(tmp_path, None) == cfg

    def test_walks_up_to_a_parent(self, tmp_path):
        cfg = write(tmp_path / "latexfmt.toml", "columns = 80\n")
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        assert find_config(deep, None) == cfg

    def test_explicit_path_wins(self, tmp_path):
        write(tmp_path / "latexfmt.toml", "columns = 80\n")
        other = write(tmp_path / "other.toml", "columns = 70\n")
        assert find_config(tmp_path, str(other)) == other

    def test_explicit_missing_path_is_an_error(self, tmp_path):
        with pytest.raises(LatexfmtError, match="config file not found"):
            find_config(tmp_path, str(tmp_path / "nope.toml"))

    def test_pyproject_without_our_table_is_skipped(self, tmp_path):
        write(tmp_path / "pyproject.toml", '[project]\nname = "unrelated"\n')
        assert find_config(tmp_path, None) is None

    def test_pyproject_with_our_table_is_used(self, tmp_path):
        cfg = write(tmp_path / "pyproject.toml",
                    '[project]\nname = "x"\n\n[tool.latexfmt]\ncolumns = 80\n')
        assert find_config(tmp_path, None) == cfg

    def test_malformed_toml_does_not_crash_discovery(self, tmp_path):
        write(tmp_path / "latexfmt.toml", "this is not = = toml\n")
        assert find_config(tmp_path, None) is None


class TestLoading:
    def test_defaults_when_no_file(self):
        assert load_config(None) == Config()

    def test_standalone_top_level_keys(self, tmp_path):
        cfg = load_config(write(tmp_path / "latexfmt.toml",
                                "columns = 80\nindent = 4\nbuild = false\n"))
        assert (cfg.columns, cfg.indent, cfg.build) == (80, 4, False)

    def test_tool_table_in_pyproject(self, tmp_path):
        cfg = load_config(write(tmp_path / "pyproject.toml",
                                "[tool.latexfmt]\ncolumns = 72\n"))
        assert cfg.columns == 72

    def test_unknown_keys_are_ignored(self, tmp_path):
        cfg = load_config(write(tmp_path / "latexfmt.toml",
                                "columns = 80\nnot_a_real_key = 1\n"))
        assert cfg.columns == 80
        assert not hasattr(cfg, "not_a_real_key")

    def test_malformed_explicit_toml_is_a_user_error(self, tmp_path):
        path = write(tmp_path / "latexfmt.toml", "not valid = = toml\n")
        with pytest.raises(LatexfmtError, match="invalid TOML"):
            load_config(path)

    def test_non_table_tool_configuration_is_a_user_error(self, tmp_path):
        path = write(tmp_path / "pyproject.toml", '[tool]\nlatexfmt = "wrong"\n')
        with pytest.raises(LatexfmtError, match="must be a table"):
            load_config(path)


class TestValidation:
    @pytest.mark.parametrize("cfg", [
        Config(columns="wide"),
        Config(columns=0),
        Config(indent=-1),
        Config(build="yes"),
        Config(exclude="*.tex"),
        Config(exclude=[1]),
    ])
    def test_invalid_values_are_rejected(self, cfg):
        with pytest.raises(LatexfmtError, match="config"):
            validate_config(cfg)

    def test_unknown_encoding_is_rejected(self):
        with pytest.raises(LatexfmtError, match="unknown source encoding"):
            validate_config(Config(encoding="not-a-codec"))


class TestPrecedence:
    def _args(self, *argv):
        return build_parser().parse_args(["main.tex", *argv])

    def test_cli_overrides_file(self):
        cfg = _merge(Config(columns=80), self._args("--columns", "70"))
        assert cfg.columns == 70

    def test_absent_flag_leaves_file_value(self):
        cfg = _merge(Config(columns=80), self._args())
        assert cfg.columns == 80

    def test_negative_flags_override_a_true_file_value(self):
        cfg = _merge(Config(build=True, latexindent=True),
                     self._args("--no-build", "--no-latexindent"))
        assert not cfg.build and not cfg.latexindent

    def test_keep_labels_flips_prune(self):
        assert not _merge(Config(), self._args("--keep-labels")).prune_labels

"""Configuration: defaults, TOML loading, and external-tool detection."""

from __future__ import annotations

import codecs
import shutil
import tomllib
from dataclasses import dataclass, field, fields
from importlib import resources
from pathlib import Path

from .texutil import LatexfmtError


@dataclass
class Config:
    columns: int = 100
    indent: int = 2
    prune_labels: bool = True
    wrap_comments: bool = False
    build: bool = True
    latexindent: bool = True
    latexindent_config: str = ".latexindent.yaml"
    encoding: str = "utf-8"
    strict: bool = False
    all: bool = False
    backup: bool = False
    exclude: list[str] = field(default_factory=lambda: ["*_old*", "*sections_old*"])


_KEYS = {f.name for f in fields(Config)}


def _read_toml_table(path: Path) -> dict:
    """Return the config table from ``path``.

    Supports a standalone file (top-level keys) and a ``[tool.latexfmt]`` table
    (as in ``pyproject.toml``).
    """
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    tool = data.get("tool", {})
    if path.name == "pyproject.toml":
        return tool.get("latexfmt", {}) if isinstance(tool, dict) else {}
    if isinstance(tool, dict) and "latexfmt" in tool:
        return tool["latexfmt"]
    return data


def find_config(start: Path, explicit: str | None) -> Path | None:
    """Locate a config file: explicit path, else ``latexfmt.toml`` /
    ``pyproject.toml`` walking up from ``start``."""
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise LatexfmtError(f"config file not found: {p}")
        return p
    for d in [start, *start.parents]:
        for name in ("latexfmt.toml", "pyproject.toml"):
            cand = d / name
            if cand.is_file():
                try:
                    if _read_toml_table(cand):
                        return cand
                except (OSError, tomllib.TOMLDecodeError):
                    pass
    return None


def load_config(config_path: Path | None) -> Config:
    cfg = Config()
    if config_path is None:
        return cfg
    try:
        table = _read_toml_table(config_path)
    except tomllib.TOMLDecodeError as exc:
        raise LatexfmtError(f"invalid TOML in {config_path}: {exc}") from exc
    except OSError as exc:
        raise LatexfmtError(f"cannot read config {config_path}: {exc}") from exc
    if not isinstance(table, dict):
        raise LatexfmtError(f"latexfmt configuration in {config_path} must be a table")
    for key, value in table.items():
        if key in _KEYS:
            setattr(cfg, key, value)
    return cfg


def validate_config(cfg: Config) -> None:
    """Reject invalid config values before any project files are processed."""
    for name in ("columns", "indent"):
        value = getattr(cfg, name)
        if type(value) is not int or value < (1 if name == "columns" else 0):
            requirement = (
                "a positive integer" if name == "columns"
                else "a non-negative integer"
            )
            raise LatexfmtError(f"config {name} must be {requirement}")
    for name in ("prune_labels", "wrap_comments", "build", "latexindent",
                 "strict", "all", "backup"):
        if type(getattr(cfg, name)) is not bool:
            raise LatexfmtError(f"config {name} must be a boolean")
    for name in ("latexindent_config", "encoding"):
        value = getattr(cfg, name)
        if not isinstance(value, str) or not value:
            raise LatexfmtError(f"config {name} must be a non-empty string")
    if not isinstance(cfg.exclude, list) or not all(
            isinstance(item, str) for item in cfg.exclude):
        raise LatexfmtError("config exclude must be an array of strings")
    try:
        codecs.lookup(cfg.encoding)
    except LookupError as exc:
        raise LatexfmtError(f"unknown source encoding: {cfg.encoding}") from exc


@dataclass
class Tools:
    latexindent: str | None
    latexmk: str | None


def detect_tools() -> Tools:
    return Tools(latexindent=shutil.which("latexindent"),
                 latexmk=shutil.which("latexmk"))


def packaged_latexindent_config() -> Path:
    """Path to the ``.latexindent.yaml`` shipped with latexfmt.

    Used as a fallback: without a config, ``latexindent`` runs with *its* own
    defaults (tab indent, ``&`` re-padding, no protected environments), which
    undoes latexfmt's earlier passes and produces output that latexfmt's own
    verifier then flags.
    """
    return Path(str(resources.files("latexfmt") / "data" / "latexindent.yaml"))

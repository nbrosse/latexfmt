"""Configuration: defaults, TOML loading, and external-tool detection."""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    columns: int = 100
    indent: int = 2
    prune_labels: bool = True
    wrap_comments: bool = False
    build: bool = True
    latexindent: bool = True
    latexindent_config: str = ".latexindent.yaml"
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
    if path.name == "pyproject.toml":
        return data.get("tool", {}).get("latexfmt", {})
    if "tool" in data and "latexfmt" in data.get("tool", {}):
        return data["tool"]["latexfmt"]
    return data


def find_config(start: Path, explicit: str | None) -> Path | None:
    """Locate a config file: explicit path, else ``latexfmt.toml`` /
    ``pyproject.toml`` walking up from ``start``."""
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
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
    table = _read_toml_table(config_path)
    for key, value in table.items():
        if key in _KEYS:
            setattr(cfg, key, value)
    return cfg


@dataclass
class Tools:
    latexindent: str | None
    latexmk: str | None


def detect_tools() -> Tools:
    return Tools(latexindent=shutil.which("latexindent"),
                 latexmk=shutil.which("latexmk"))

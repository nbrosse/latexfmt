"""Package version, resolved from installed metadata (pyproject is the source)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("latexfmt")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0.0.0+unknown"

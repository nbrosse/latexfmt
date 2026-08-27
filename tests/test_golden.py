"""Golden-file tests for the pure text pipeline.

Each ``cases/<name>/`` holds ``in.tex``, the expected ``expected.tex``, and an
optional ``opts.json`` (``refs`` plus any ``transform_text`` keyword).

These exercise ``transform_text`` only -- deliberately not latexindent, whose
output would vary with the installed Perl tool's version and make the goldens
flaky. The CLI wiring is covered by ``test_cli.py``.

Regenerate after an intentional change with::

    LATEXFMT_REGOLD=1 uv run pytest tests/test_golden.py

and read the resulting diff before committing it.
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from latexfmt.transform import transform_text

CASES_DIR = pathlib.Path(__file__).parent / "cases"
CASES = sorted(p for p in CASES_DIR.iterdir() if p.is_dir())
REGOLD = os.environ.get("LATEXFMT_REGOLD") == "1"


def _run(case: pathlib.Path, text: str) -> tuple[str, list[str]]:
    opts_file = case / "opts.json"
    opts = json.loads(opts_file.read_text()) if opts_file.is_file() else {}
    opts.setdefault("autonum", False)
    refs = set(opts.pop("refs", []))
    return transform_text(text, refs=refs, **opts)


def test_cases_exist():
    assert CASES, f"no golden cases found under {CASES_DIR}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_golden(case: pathlib.Path):
    out, _ = _run(case, (case / "in.tex").read_text())
    expected_file = case / "expected.tex"
    if REGOLD:
        expected_file.write_text(out)
        pytest.skip(f"regenerated {case.name}")
    assert expected_file.is_file(), (
        f"{case.name} has no expected.tex; run with LATEXFMT_REGOLD=1")
    assert out == expected_file.read_text()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_idempotent(case: pathlib.Path):
    """Formatting formatted output must be a no-op.

    A formatter that keeps changing its own output cannot be trusted in a
    pre-commit hook, and drift here usually means a pass is fighting another.
    """
    once, _ = _run(case, (case / "in.tex").read_text())
    twice, _ = _run(case, once)
    assert twice == once, f"{case.name} is not idempotent"

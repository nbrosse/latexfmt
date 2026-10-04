# latexfmt

`latexfmt` formats a LaTeX project to a set of house conventions. Point it at a
root `.tex`; it resolves every `\input`/`\include` and formats the body files.
As in TeX, an input path is relative to the root's directory wherever the
`\input` sits (the including file's directory is tried as a fallback). An input
that resolves to no file is reported, and label pruning is then turned off,
since a reference inside that file would be invisible.

## Installation

`latexfmt` requires Python 3.13 or newer. Install the command directly from the
Git repository into an isolated `uv` tool environment:

```console
uv tool install git+https://github.com/nbrosse/latexfmt.git
latexfmt --version
```

Re-run the install with `--reinstall`, for example
`uv tool install --reinstall git+https://github.com/nbrosse/latexfmt.git@dev`,
to replace an existing installation. If `uv` reports that its executable
directory is missing from `PATH`, run `uv tool update-shell` once.

For development without installation, point `uv run --project` or `uvx --from`
at a local checkout.

## Usage

```console
# from the LaTeX project directory
latexfmt main.tex             # format + verify with latexmk
latexfmt main.tex --dry-run   # unified diff, change nothing
latexfmt main.tex --check     # summary only, exit 1 if it would change

# development checkout alternatives
uv run --project /path/to/latexfmt latexfmt main.tex
uvx --from /path/to/latexfmt latexfmt main.tex
```

### Exit codes

| code | meaning |
| ---- | ------- |
| `0`  | success |
| `1`  | files would be reformatted (`--check` / `--dry-run` only) |
| `2`  | usage or I/O error (missing root, undecodable file) |
| `3`  | `latexmk` build failed, or `--strict` and the verify pass found something |

`--check` follows the `black`/`ruff` convention, so `latexfmt main.tex --check`
works directly in CI or a pre-commit hook.

All transformations are prepared before the first write, individual writes
replace files atomically, and a strict-verification or `latexmk` failure restores
the original sources. TeX build artifacts are not rolled back.

## What it does

In order, per file: normalize whitespace (tabs → spaces, strip trailing) · prune
unreferenced `\label`s **inside display math** (referenced-anywhere is
auto-detected across the whole project) · pick math environments (single-row
`align` → `equation`, keep multi-row `align`; autonum-aware,
numbering-preserving) · indent 2 spaces per environment level with `proof`
bodies flush-left · reflow prose to 100 columns (VSCode *Rewrap*-style) ·
standardize equation bodies (compact, wrapped at 100, AMS break-before-operator,
no orphan operators) · collapse blank lines. It then finalizes indentation with
`latexindent` and, unless `--no-build`, rebuilds with `latexmk`, failing on
undefined or multiply-defined references.

Opaque environments — `tabular`, `tabularx`, `longtable`, `verbatim`,
`lstlisting`, `minted`, `tikzpicture`, `comment` — are left byte-for-byte alone
by every pass, and are exempt from the verify checks. Hand-aligned tables keep
their tabs.

Comments are preserved everywhere, including inside display math. With
`--wrap-comments`, only full-line comment paragraphs are reflowed and every
continuation line retains its `%` marker; trailing comments remain untouched. A
commented-out `\label` is never pruned nor promoted to a live one, and a `\\`,
`&` or `\end{...}` inside a comment never changes how a block is parsed.

Missing `latexindent`/`latexmk` are detected and skipped with a warning (the
built-in Python indentation is used as a fallback).

### Flags

`--columns` · `--indent` · `--encoding` · `--all` (also format root + preamble) ·
`--keep-labels` · `--wrap-comments` · `--no-latexindent` · `--no-build` ·
`--backup` · `--strict` · `--dry-run` · `--check` · `--version`. CLI flags
override the config file, which overrides the built-in defaults. See
`latexfmt.toml` for every option.

## Configuration

Installing the tool does not install a project configuration. Put a
`latexfmt.toml` in the LaTeX project, normally beside `main.tex`:

```toml
columns = 100
indent = 2
encoding = "utf-8"
prune_labels = true
wrap_comments = false
build = true
latexindent = true
latexindent_config = ".latexindent.yaml"
strict = false
all = false
backup = false
exclude = ["*_old*", "*sections_old*"]
```

The same keys can instead live under `[tool.latexfmt]` in a project's
`pyproject.toml`:

```toml
[tool.latexfmt]
columns = 100
indent = 2
build = true
```

Configuration precedence is: CLI flags, then the project configuration, then
built-in defaults. `latexfmt` discovers a configuration by walking upward from
the directory containing the root `.tex`; discovery does not start from the
shell's current directory or from the installed package. Pass
`--config /path/to/config.toml` to select a file explicitly. A missing explicit
file or an invalid value is reported as an error before source files are
processed.

`latexindent_config` names a separate YAML configuration consumed by
`latexindent`; a relative path is resolved from the root `.tex` directory. It
does not refer to `latexfmt.toml` itself.

If no `.latexindent.yaml` is found, latexfmt falls back to the copy bundled in
the installed package and says so in the summary. This matters because running
`latexindent` without that YAML would apply its own defaults—tab indentation,
`&` column re-padding, and no protected verbatim/tikz/tabular environments—which
would undo earlier formatting passes. The `.latexindent.yaml` in this repository
matches the bundled copy and can be copied into a project when customization is
needed.

## Relation to `latexindent` and `tex-fmt`

`latexfmt` is not a competing formatter — it is a project-level, semantics-aware
pipeline that *uses* a line formatter as its final indentation step.
[`latexindent`](https://github.com/cmhughes/latexindent.pl) (Perl) is that backend
today; [`tex-fmt`](https://github.com/WGUNDERWOOD/tex-fmt) (Rust) is a faster,
Perl-free alternative in the same category. Both are pure line/whitespace
formatters: by their own scope they do *no* semantic parsing, so neither does the
work that motivates this package — selecting math environments (`align` →
`equation`, numbering-preserving, autonum-aware), standardizing equation bodies,
pruning unreferenced `\label`s across the project, resolving `\input`/`\include`,
or verifying the result with a `latexmk` build.

`tex-fmt` is not wired in as a backend for the moment. It could later slot into the
same finalizer seam as `latexindent` (run with `--nowrap`, since `latexfmt` already
reflows prose itself), but doing so trades `latexindent`'s fine-grained convention
fidelity (see `.latexindent.yaml`: `proof` bodies flush-left, no `&` re-padding,
protected verbatim/tikz/tabular blocks) for speed and a lighter dependency. Until
that tradeoff is worth wiring up, `latexfmt` stays on `latexindent`.

## Development

```console
uv sync            # install with dev dependencies
uv run pytest      # 137 hermetic tests, plus 4 integration tests if TeX is installed
uv run ruff check .
```

The suite is golden-file based: `tests/cases/<name>/` holds `in.tex`,
`expected.tex` and an optional `opts.json`. Every case is also asserted
**idempotent** — reformatting formatted output must be a no-op. After an
intentional change, regenerate with

```console
LATEXFMT_REGOLD=1 uv run pytest tests/test_golden.py
```

and read the resulting diff before committing it.

`tests/test_integration.py` is the only part that shells out to the real
`latexindent` and `latexmk`; it skips itself when they are not on `PATH`.

## License

Apache 2.0 — see `LICENSE`.

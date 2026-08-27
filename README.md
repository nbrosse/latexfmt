# latexfmt

`latexfmt` formats a LaTeX project to a set of house conventions. Point it at a
root `.tex`; it resolves every `\input`/`\include` and formats the body files.

## Usage

The tool is not installed globally — run it from the target LaTeX project with
`uv run --project` (or `uvx --from`) pointing at this repo:

```console
# from the LaTeX project directory
uv run --project /home/nicolas/PycharmProjects/postdoc/latexfmt latexfmt main_jmlr.tex          # format + verify (latexmk)
uv run --project /home/nicolas/PycharmProjects/postdoc/latexfmt latexfmt main_jmlr.tex --dry-run  # show a unified diff, change nothing
uvx --from /home/nicolas/PycharmProjects/postdoc/latexfmt latexfmt main_jmlr.tex                 # equivalent, no project needed
```

## What it does

In order, per file: normalize whitespace (tabs -> spaces, strip trailing) · prune
unreferenced `\label`s (auto-detected across the whole project) · pick math
environments (single-line `align` -> `equation`, keep multi-line `align`;
autonum-aware, numbering-preserving) · indent 2 spaces per environment level with
`proof` bodies flush-left · reflow prose to 100 columns (VSCode *Rewrap*-style) ·
standardize equation bodies (compact, wrapped at 100, AMS break-before-operator, no
orphan operators) · collapse blank lines. It then finalizes indentation with
`latexindent` (using `.latexindent.yaml`) and, unless `--no-build`, rebuilds with
`latexmk`, failing loudly on undefined/multiply-defined references.

Missing `latexindent`/`latexmk` are detected and skipped with a warning (the
built-in Python indentation is used as a fallback). Behavior is configurable via
`latexfmt.toml` (or a `[tool.latexfmt]` table in `pyproject.toml`); CLI flags
override the file. Key flags: `--columns`, `--indent`, `--all` (also format root +
preamble), `--keep-labels`, `--wrap-comments`, `--no-latexindent`, `--no-build`,
`--backup`, `--dry-run`. See `latexfmt.toml` for all options.

## Relation to `latexindent` and `tex-fmt`

`latexfmt` is not a competing formatter — it is a project-level, semantics-aware
pipeline that *uses* a line formatter as its final indentation step.
[`latexindent`](https://github.com/cmhughes/latexindent.pl) (Perl) is that backend
today; [`tex-fmt`](https://github.com/WGUNDERWOOD/tex-fmt) (Rust) is a faster,
Perl-free alternative in the same category. Both are pure line/whitespace
formatters: by their own scope they do *no* semantic parsing, so neither does the
work that motivates this package — selecting math environments (`align` ->
`equation`, numbering-preserving, autonum-aware), standardizing equation bodies,
pruning unreferenced `\label`s across the project, resolving `\input`/`\include`,
or verifying the result with a `latexmk` build.

`tex-fmt` is not wired in as a backend for the moment. It could later slot into the
same finalizer seam as `latexindent` (run with `--nowrap`, since `latexfmt` already
reflows prose itself), but doing so trades `latexindent`'s fine-grained convention
fidelity (see `.latexindent.yaml`: `proof` bodies flush-left, no `&` re-padding,
protected verbatim/tikz/tabular blocks) for speed and a lighter dependency. Until
that tradeoff is worth wiring up, `latexfmt` stays on `latexindent`.

## Config discovery

`latexfmt` looks for `latexfmt.toml` (or a `[tool.latexfmt]` `pyproject.toml`
table) by walking **up from the current working directory** — not from this repo.
The `latexfmt.toml` and `.latexindent.yaml` shipped here are therefore *defaults /
examples*: a run launched from a LaTeX project elsewhere on disk will **not**
auto-find them and falls back to built-in defaults. `latexindent_config` inside
`latexfmt.toml` (`.latexindent.yaml`) is likewise resolved relative to the CWD.

To format a project with this repo's config, either:

- pass `--config /home/nicolas/PycharmProjects/postdoc/latexfmt/latexfmt.toml`
  (and set its `latexindent_config` to an absolute path, or use `--no-latexindent`), or
- copy `latexfmt.toml` + `.latexindent.yaml` into the project directory before
  formatting.

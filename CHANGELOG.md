# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Nested `\input`/`\include` paths are resolved against the root's directory, as
  TeX does, instead of the directory of the including file. Before, an
  `\input{figures/fig.tex}` inside `sections/sec.tex` was silently skipped: the
  file was neither formatted nor scanned for references, so a label referenced
  only from it was pruned as dead, breaking the reference. The including file's
  directory is still tried as a fallback.
- Files matched by `exclude` (and the files they input) are still scanned for
  references, though never formatted: they are compiled, so a label referenced
  only from one of them is live. Before, such a label was pruned.
- `.tex` is appended to an input name instead of replacing its last suffix
  (`\input{fig.v2}` reads `fig.v2.tex`, not `fig.tex`).

### Changed

- An input that resolves to no file is reported in the summary instead of being
  skipped silently, and label pruning is turned off for that run (as with
  `--keep-labels`), since references inside the missing file are unknown.
- Files reached through nested inputs that were previously skipped (see above)
  are now formatted like any other body file. Use `exclude` in `latexfmt.toml` to
  keep generated or hand-tuned files untouched.

## [0.1.0] - 2026-08-27

Initial release.

[Unreleased]: https://github.com/nbrosse/latexfmt/compare/855419b...HEAD
[0.1.0]: https://github.com/nbrosse/latexfmt/commit/855419b

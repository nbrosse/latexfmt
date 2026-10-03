"""Command-line interface and orchestration for ``latexfmt``."""

from __future__ import annotations

import argparse
import difflib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ._version import __version__
from .config import (
    Config,
    detect_tools,
    find_config,
    load_config,
    packaged_latexindent_config,
    validate_config,
)
from .texutil import (
    LatexfmtError,
    collect_referenced_labels,
    detect_autonum,
    read_text,
    resolve_project,
    write_text,
)
from .transform import transform_text
from .verify import check_files, scan_build_log

# Exit codes (documented in the README; --check follows the black convention).
EXIT_OK = 0
EXIT_WOULD_CHANGE = 1
EXIT_USAGE = 2
EXIT_FAILED = 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="latexfmt",
        description="Format a LaTeX project to house conventions "
                    "(math standardization, indentation, prose reflow).",
        epilog="exit codes: 0 ok · 1 would reformat (--check/--dry-run) · "
               "2 usage or I/O error · 3 build failed (or --strict findings)",
    )
    p.add_argument("root", help="root .tex file (its \\input/\\include are resolved)")
    p.add_argument("--version", action="version", version=f"latexfmt {__version__}")
    p.add_argument("--columns", type=int, help="wrap width (default 100)")
    p.add_argument("--indent", type=int, help="spaces per environment level (default 2)")
    p.add_argument("--config", help="path to a latexfmt.toml / pyproject.toml")
    p.add_argument("--encoding", help="source encoding (default utf-8)")
    p.add_argument("--all", action="store_true",
                   help="also format the root and preamble files")
    p.add_argument("--keep-labels", action="store_true",
                   help="do not remove unreferenced labels")
    p.add_argument("--wrap-comments", action="store_true",
                   help="also rewrap %%-comment paragraphs")
    p.add_argument("--no-latexindent", action="store_true",
                   help="skip the latexindent finalization step")
    p.add_argument("--no-build", action="store_true",
                   help="skip the latexmk build/verify step")
    p.add_argument("--backup", action="store_true",
                   help="write <file>.orig before overwriting")
    p.add_argument("--strict", action="store_true",
                   help="exit non-zero if the verify pass reports findings")
    p.add_argument("--dry-run", action="store_true",
                   help="show a unified diff, change nothing; exit 1 if it would")
    p.add_argument("--check", action="store_true",
                   help="like --dry-run but without the diff (for CI)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _merge(cfg: Config, args: argparse.Namespace) -> Config:
    if args.columns is not None:
        cfg.columns = args.columns
    if args.indent is not None:
        cfg.indent = args.indent
    if args.encoding is not None:
        cfg.encoding = args.encoding
    if args.all:
        cfg.all = True
    if args.keep_labels:
        cfg.prune_labels = False
    if args.wrap_comments:
        cfg.wrap_comments = True
    if args.no_latexindent:
        cfg.latexindent = False
    if args.no_build:
        cfg.build = False
    if args.backup:
        cfg.backup = True
    if args.strict:
        cfg.strict = True
    return cfg


def _run_latexindent(text: str, cfg_path: Path, tool: str) -> str | None:
    """Run latexindent on ``text`` and return its output, or None on failure.

    Runs entirely inside a scratch directory: latexindent drops an ``indent.log``
    in its working directory, which in the project directory would clobber a
    user's file, and a crash would strand a stray .tex where latexmk can see it.
    Uses stdout mode, so no backup files are produced.
    """
    cmd = [tool]
    if cfg_path.is_file():
        cmd += ["-l", str(cfg_path.resolve())]
    with tempfile.TemporaryDirectory(prefix="latexfmt-") as td:
        tmp = Path(td) / "body.tex"
        tmp.write_text(text, encoding="utf-8")
        try:
            r = subprocess.run([*cmd, str(tmp)], capture_output=True, text=True,
                               cwd=td, timeout=300)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return r.stdout


def _relpath(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:  # different drive on Windows
        return str(path)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except LatexfmtError as exc:
        print(f"latexfmt: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("latexfmt: interrupted", file=sys.stderr)
        return EXIT_USAGE


def _main(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    if not root.is_file():
        print(f"latexfmt: root file not found: {root}", file=sys.stderr)
        return EXIT_USAGE

    root = root.resolve()
    workdir = root.parent
    preview = args.dry_run or args.check
    cfg = _merge(load_config(find_config(workdir, args.config)), args)
    validate_config(cfg)

    tools = detect_tools()
    cfg_path = Path(cfg.latexindent_config)
    if not cfg_path.is_absolute():
        cfg_path = workdir / cfg_path

    proj = resolve_project(root, cfg.exclude, cfg.encoding)
    autonum = detect_autonum(proj.all_files, cfg.encoding)
    refs = collect_referenced_labels(proj.all_files, cfg.encoding)

    # (path, minimal): preamble/macro files get whitespace-only treatment and
    # never see latexindent, so macro-definition bodies are never re-indented.
    if cfg.all:
        targets = ([(root, False)]
                   + [(p, True) for p in proj.preamble_files]
                   + [(p, False) for p in proj.body_files])
    else:
        targets = [(p, False) for p in proj.body_files]

    warnings: list[str] = []
    for parent, name in proj.missing:
        warnings.append(f"\\input{{{name}}} in {_relpath(parent, workdir)}: not found "
                        "-> not formatted, its references not scanned")
    if proj.missing and cfg.prune_labels:
        # A reference in an unseen file would make its label look dead.
        cfg.prune_labels = False
        warnings.append("unresolved inputs -> label pruning disabled (as --keep-labels)")
    use_latexindent = cfg.latexindent and tools.latexindent is not None
    if cfg.latexindent and tools.latexindent is None:
        warnings.append("latexindent not found on PATH -> skipping (Python "
                        "indentation used instead)")
    if use_latexindent and not cfg_path.is_file():
        # Without a config latexindent applies its own defaults (tab indent,
        # '&' re-padding, no protected verbatim/tikz/tabular), undoing earlier
        # passes. Fall back to the copy shipped with latexfmt.
        fallback = packaged_latexindent_config()
        warnings.append(f"latexindent config not found: {cfg_path} -> using "
                        f"latexfmt's bundled defaults ({fallback})")
        cfg_path = fallback

    changed: list[Path] = []
    all_removed: list[str] = []
    prepared: list[tuple[Path, str, str]] = []

    for path, minimal in targets:
        original = read_text(path, cfg.encoding)
        try:
            new, removed = transform_text(
                original, refs=refs, autonum=autonum, columns=cfg.columns,
                indent=cfg.indent, wrap_comments=cfg.wrap_comments,
                prune_labels=cfg.prune_labels, minimal=minimal,
            )
        except LatexfmtError as exc:
            raise LatexfmtError(f"{path}: {exc}") from exc
        if use_latexindent and not minimal:
            li = _run_latexindent(new, cfg_path, tools.latexindent)
            if li is None:
                warnings.append(f"latexindent failed on {path.name}; kept Python output")
            else:
                new = li
        all_removed.extend(removed)
        if new == original:
            continue
        changed.append(path)
        prepared.append((path, original, new))
        if preview and args.dry_run:
            sys.stdout.writelines(difflib.unified_diff(
                original.splitlines(True), new.splitlines(True),
                fromfile=str(path), tofile=str(path) + " (formatted)"))
    if preview:
        _report(cfg, targets, changed, all_removed, autonum, preview,
                warnings, tools, root, workdir)
        return EXIT_WOULD_CHANGE if changed else EXIT_OK

    if cfg.backup:
        for path, original, _ in prepared:
            write_text(path.with_suffix(path.suffix + ".orig"), original,
                       cfg.encoding)

    written: list[tuple[Path, str, str]] = []
    try:
        for update in prepared:
            path, _, new = update
            write_text(path, new, cfg.encoding)
            written.append(update)
        status = _report(cfg, targets, changed, all_removed, autonum, preview,
                         warnings, tools, root, workdir)
    except (Exception, KeyboardInterrupt):
        _restore_sources(written, cfg.encoding)
        raise
    if status != EXIT_OK and written:
        _restore_sources(written, cfg.encoding)
        print(f"  ! verification failed -> restored {len(written)} source file(s)")
    return status


def _restore_sources(updates: list[tuple[Path, str, str]], encoding: str) -> None:
    """Best-effort rollback of already-written source files."""
    errors: list[LatexfmtError] = []
    for path, original, _ in reversed(updates):
        try:
            write_text(path, original, encoding)
        except LatexfmtError as exc:
            errors.append(exc)
    if errors:
        raise LatexfmtError(
            f"rollback failed for {len(errors)} source file(s): {errors[0]}")


def _report(cfg, targets, changed, removed, autonum, preview, warnings, tools,
            root, workdir) -> int:
    """Print the summary; return the exit code for a non-preview run."""
    formatted = [p for p, _ in targets]
    verify_paths = [p for p, m in targets if not m]
    status = EXIT_OK

    print()
    print("latexfmt summary")
    print(f"  autonum: {'yes' if autonum else 'no'}   "
          f"columns: {cfg.columns}   indent: {cfg.indent}   "
          f"prune-labels: {cfg.prune_labels}")
    print(f"  files formatted: {len(formatted)}   "
          f"{'would change' if preview else 'changed'}: {len(changed)}")
    for p in changed:
        print(f"    - {_relpath(p, workdir)}")
    if removed:
        uniq = sorted(set(removed))
        print(f"  labels removed ({len(uniq)}): {', '.join(uniq)}")
    for w in warnings:
        print(f"  ! {w}")

    # Post-format verification (skipped in preview: files are unchanged on disk).
    if not preview:
        findings = check_files(verify_paths, cfg.columns, cfg.encoding)
        if findings:
            print(f"  verify: {len(findings)} finding(s)"
                  f"{' [strict]' if cfg.strict else ''}:")
            for f in findings[:20]:
                print(f"      {f}")
            if len(findings) > 20:
                print(f"      ... and {len(findings) - 20} more")
            if cfg.strict:
                status = EXIT_FAILED
        else:
            print("  verify: clean (0 lone-ops, 0 dangling &, 0 tabs/trailing, "
                  f"no >{cfg.columns}-col non-opaque lines)")

    if preview or not cfg.build:
        return status
    if tools.latexmk is None:
        print("  ! latexmk not found -> skipping build")
        return status

    print("  building (latexmk)...", flush=True)
    try:
        r = subprocess.run(
            [tools.latexmk, "-pdf", "-interaction=nonstopmode", root.name],
            capture_output=True, text=True, cwd=workdir, timeout=1800)
        rc = r.returncode
    except subprocess.TimeoutExpired:
        print("  ! latexmk timed out after 30 min")
        return EXIT_FAILED
    except OSError as exc:
        print(f"  ! latexmk could not be run: {exc}")
        return EXIT_FAILED

    log = scan_build_log(workdir / (root.stem + ".log"))
    ok = rc == 0 and log.label_problems == 0
    print(f"  build: {'ok' if ok else 'FAILED'} (exit {rc})   "
          f"undefined-refs: {log.undefined_refs}   "
          f"multiply-defined: {log.multiply_defined}   "
          f"pages: {log.pages}   overfull-hbox: {log.overfull}")
    if log.undefined_citations:
        print(f"  ! {log.undefined_citations} undefined citation(s) "
              "(bibliography, not latexfmt)")
    if not ok:
        print("  ! build problems -- inspect the .log "
              "(a removed label may have broken a \\ref)")
        status = EXIT_FAILED
    return status


if __name__ == "__main__":
    raise SystemExit(main())

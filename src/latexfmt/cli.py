"""Command-line interface and orchestration for ``latexfmt``."""

from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import Config, detect_tools, find_config, load_config
from .texutil import (
    collect_referenced_labels,
    detect_autonum,
    resolve_project,
)
from .transform import transform_text
from .verify import check_files, scan_build_log


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="latexfmt",
        description="Format a LaTeX project to house conventions "
                    "(math standardization, indentation, prose reflow).",
    )
    p.add_argument("root", help="root .tex file (its \\input/\\include are resolved)")
    p.add_argument("--columns", type=int, help="wrap width (default 100)")
    p.add_argument("--indent", type=int, help="spaces per environment level (default 2)")
    p.add_argument("--config", help="path to a latexfmt.toml / pyproject.toml")
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
    p.add_argument("--dry-run", action="store_true",
                   help="show a unified diff; change nothing")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _merge(cfg: Config, args: argparse.Namespace) -> Config:
    if args.columns is not None:
        cfg.columns = args.columns
    if args.indent is not None:
        cfg.indent = args.indent
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
    return cfg


def _run_latexindent(text: str, cfg_path: Path, tool: str, workdir: Path) -> str | None:
    """Run latexindent on ``text`` (via a temp file) and return its output, or
    None on failure. Uses stdout mode so no backup files are created.

    Note: do NOT pass ``-s`` here -- silent mode suppresses the formatted
    document on stdout, not just the log."""
    cmd = [tool]
    if cfg_path.is_file():
        cmd += ["-l", str(cfg_path)]
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".tex", dir=workdir,
                                         delete=False, encoding="utf-8") as tf:
            tf.write(text)
            tmp = Path(tf.name)
        r = subprocess.run(cmd + [str(tmp)], capture_output=True, text=True,
                           cwd=workdir)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return r.stdout
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        (workdir / "indent.log").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    if not root.is_file():
        print(f"latexfmt: root file not found: {root}", file=sys.stderr)
        return 2

    root = root.resolve()
    workdir = root.parent
    cfg = _merge(load_config(find_config(workdir, args.config)), args)
    tools = detect_tools()
    cfg_path = Path(cfg.latexindent_config)
    if not cfg_path.is_absolute():
        cfg_path = workdir / cfg_path

    proj = resolve_project(root, cfg.exclude)
    autonum = detect_autonum(proj.all_files)
    refs = collect_referenced_labels(proj.all_files)

    # (path, minimal): preamble/macro files get whitespace-only treatment and
    # never see latexindent, so macro-definition bodies are never re-indented.
    if cfg.all:
        targets = ([(root, False)]
                   + [(p, True) for p in proj.preamble_files]
                   + [(p, False) for p in proj.body_files])
    else:
        targets = [(p, False) for p in proj.body_files]

    warnings: list[str] = []
    use_latexindent = cfg.latexindent and tools.latexindent is not None
    if cfg.latexindent and tools.latexindent is None:
        warnings.append("latexindent not found on PATH -> skipping (Python "
                        "indentation used instead)")

    changed: list[Path] = []
    all_removed: list[str] = []

    for path, minimal in targets:
        original = path.read_text(encoding="utf-8")
        new, removed = transform_text(
            original, refs=refs, autonum=autonum, columns=cfg.columns,
            indent=cfg.indent, wrap_comments=cfg.wrap_comments,
            prune_labels=cfg.prune_labels, minimal=minimal,
        )
        if use_latexindent and not minimal:
            li = _run_latexindent(new, cfg_path, tools.latexindent, workdir)
            if li is None:
                warnings.append(f"latexindent failed on {path.name}; kept Python output")
            else:
                new = li
        all_removed.extend(removed)
        if new == original:
            continue
        changed.append(path)
        if args.dry_run:
            diff = difflib.unified_diff(
                original.splitlines(True), new.splitlines(True),
                fromfile=str(path), tofile=str(path) + " (formatted)")
            sys.stdout.writelines(diff)
        else:
            if cfg.backup:
                path.with_suffix(path.suffix + ".orig").write_text(
                    original, encoding="utf-8")
            path.write_text(new, encoding="utf-8")

    formatted = [p for p, _ in targets]
    verify_paths = [p for p, m in targets if not m]
    _report(cfg, formatted, verify_paths, changed, all_removed, autonum,
            args.dry_run, warnings, tools, root, workdir)
    return 0


def _report(cfg, formatted, verify_paths, changed, removed, autonum, dry_run,
            warnings, tools, root, workdir) -> None:
    rel = lambda p: str(p.relative_to(workdir)) if workdir in p.parents or p == root \
        else str(p)
    print()
    print("latexfmt summary")
    print(f"  autonum: {'yes' if autonum else 'no'}   "
          f"columns: {cfg.columns}   indent: {cfg.indent}   "
          f"prune-labels: {cfg.prune_labels}")
    print(f"  files formatted: {len(formatted)}   "
          f"{'would change' if dry_run else 'changed'}: {len(changed)}")
    for p in changed:
        print(f"    - {rel(p)}")
    if removed:
        uniq = sorted(set(removed))
        print(f"  labels removed ({len(uniq)}): {', '.join(uniq)}")
    for w in warnings:
        print(f"  ! {w}")

    # Post-format verification (skip in dry-run; files unchanged on disk).
    if not dry_run:
        findings = check_files(verify_paths, cfg.columns)
        if findings:
            print(f"  verify: {len(findings)} finding(s):")
            for f in findings[:20]:
                print(f"      {f}")
        else:
            print("  verify: clean (0 lone-ops, 0 dangling &, 0 tabs/trailing, "
                  f"no >{cfg.columns}-col non-opaque lines)")

    # Optional build.
    if not dry_run and cfg.build:
        if tools.latexmk is None:
            print("  ! latexmk not found -> skipping build")
            return
        print("  building (latexmk)...", flush=True)
        r = subprocess.run(
            [tools.latexmk, "-pdf", "-interaction=nonstopmode", root.name],
            capture_output=True, text=True, cwd=workdir)
        log = workdir / (root.stem + ".log")
        bad, pages, overfull = scan_build_log(log)
        status = "ok" if r.returncode == 0 and bad == 0 else "FAILED"
        print(f"  build: {status} (exit {r.returncode}) "
              f"undefined/multiply-defined: {bad}   "
              f"pages: {pages}   overfull-hbox: {overfull}")
        if bad or r.returncode != 0:
            print("  ! build problems -- inspect the .log "
                  "(a removed label may have broken a \\ref)")


if __name__ == "__main__":
    raise SystemExit(main())

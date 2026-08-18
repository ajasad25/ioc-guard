"""Command line entry point. Owns exit codes; nothing else does."""
import argparse
import os
import pathlib
import subprocess
import sys
from typing import List

from .finding import Finding
from .gitdiff import compare_file
from .heuristics import run_heuristics
from .patterns import load_patterns, scan_text
from .report import render_json, render_markdown, render_text
from .walk import ScanStats, is_excluded, iter_files

EXIT_CLEAN, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2
DEFAULT_IOCS = pathlib.Path(__file__).resolve().parent.parent / "iocs.txt"


def _git_show(root: str, ref: str, path: str) -> bytes:
    proc = subprocess.run(["git", "-C", root, "show", "%s:%s" % (ref, path)],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return proc.stdout if proc.returncode == 0 else b""


def _require_ref(root: str, ref: str) -> bool:
    """True if `ref` resolves to a commit in `root`.

    A base ref that silently resolves to nothing would disable the
    .gitignore and CRLF rules with no signal at all -- the scan would
    report clean while two of its rules never ran.
    """
    proc = subprocess.run(
        ["git", "-C", root, "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


def _changed_paths(root: str, base_ref: str, head_ref: str) -> List[str]:
    """Paths changed between two refs, NUL-delimited.

    Without -z, git's default core.quotePath=true returns C-quoted, octal-
    escaped names for anything non-ASCII -- "caf\\303\\251.js" -- which then
    matches no real path and was dropped silently, so a wholesale CRLF flip of
    such a file produced no finding at all.
    """
    proc = subprocess.run(["git", "-C", root, "diff", "-z", "--name-only",
                           base_ref, head_ref],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError("git diff %s..%s failed: %s"
                           % (base_ref, head_ref,
                              proc.stderr.decode("utf-8", "replace").strip()))
    return [os.fsdecode(raw) for raw in proc.stdout.split(b"\0") if raw]


def _diff_findings(root: str, base_ref: str, head_ref: str) -> List[Finding]:
    findings = []
    for path in _changed_paths(root, base_ref, head_ref):
        if is_excluded(path):
            continue
        # Both sides come from git, never from the working tree. A path listed
        # by the diff but absent from the head tree is a DELETION, which for
        # .gitignore is strictly worse than editing the .env line out -- it
        # used to be skipped and reported clean.
        base = _git_show(root, base_ref, path)
        head = _git_show(root, head_ref, path)
        findings.extend(compare_file(path, base, head))
    return findings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ioc-guard",
                                description="Scan a tree for EtherHiding supply-chain worm indicators (see iocs.txt).")
    p.add_argument("--root", default=".")
    p.add_argument("--iocs", default=str(DEFAULT_IOCS))
    p.add_argument("--base-ref", default=None,
                   help="git ref to diff against; enables .gitignore and CRLF rules")
    p.add_argument("--head-ref", default="HEAD",
                   help="git ref holding the new state (default HEAD); used with --base-ref")
    p.add_argument("--diff-only", action="store_true",
                   help="run only the base-ref diff rules, skipping the tree walk")
    p.add_argument("--json", dest="json_out", default=None)
    p.add_argument("--summary", default=None, help="append a markdown summary to this file")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    iocs_path = pathlib.Path(args.iocs)
    if not iocs_path.is_file():
        sys.stderr.write("ioc-guard: ERROR: pattern file not found: %s\n" % iocs_path)
        return EXIT_ERROR
    try:
        patterns = load_patterns(iocs_path)
    except Exception as exc:
        sys.stderr.write("ioc-guard: ERROR: cannot compile patterns: %s\n" % exc)
        return EXIT_ERROR
    if not patterns:
        sys.stderr.write("ioc-guard: ERROR: pattern file is empty: %s\n" % iocs_path)
        return EXIT_ERROR

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        sys.stderr.write("ioc-guard: ERROR: not a directory: %s\n" % root)
        return EXIT_ERROR

    if args.diff_only and not args.base_ref:
        sys.stderr.write("ioc-guard: ERROR: --diff-only requires --base-ref.\n")
        return EXIT_ERROR

    if args.base_ref and not _require_ref(root, args.base_ref):
        sys.stderr.write(
            "ioc-guard: ERROR: cannot resolve --base-ref %r in %s.\n"
            "  Refusing to report a scan whose diff rules never ran.\n"
            % (args.base_ref, root))
        return EXIT_ERROR

    if args.base_ref and not _require_ref(root, args.head_ref):
        sys.stderr.write(
            "ioc-guard: ERROR: cannot resolve --head-ref %r in %s.\n"
            "  Refusing to report a scan whose diff rules never ran.\n"
            % (args.head_ref, root))
        return EXIT_ERROR

    findings = []
    stats = ScanStats()
    try:
        if not args.diff_only:
            for relpath, text in iter_files(root, stats):
                findings.extend(scan_text(text, patterns, relpath))
                findings.extend(run_heuristics(text, relpath))
        if args.base_ref:
            findings.extend(_diff_findings(root, args.base_ref, args.head_ref))
    except Exception as exc:
        sys.stderr.write("ioc-guard: ERROR: scan failed: %s\n" % exc)
        return EXIT_ERROR

    # A file the walk never opened is not a clean file. Report the gap on
    # stderr so it survives --quiet and shows up in CI logs and hook output.
    if stats.skipped:
        sys.stderr.write("ioc-guard: skipped %d file(s) (binary, >8MB, symlink or unreadable):\n"
                         % stats.skipped)
        for line in stats.describe():
            sys.stderr.write(line + "\n")

    findings = sorted(set(findings), key=lambda f: (f.path, f.line, f.rule))

    if args.json_out:
        try:
            pathlib.Path(args.json_out).write_text(render_json(findings), encoding="utf-8")
        except OSError as exc:
            sys.stderr.write("ioc-guard: ERROR: cannot write --json %s: %s\n"
                             % (args.json_out, exc))
            return EXIT_ERROR
    if args.summary:
        try:
            with open(args.summary, "a", encoding="utf-8") as fh:
                fh.write(render_markdown(findings))
        except OSError as exc:
            sys.stderr.write("ioc-guard: ERROR: cannot write --summary %s: %s\n"
                             % (args.summary, exc))
            return EXIT_ERROR

    if not args.quiet:
        sys.stdout.write(render_text(findings))

    return EXIT_FINDINGS if findings else EXIT_CLEAN

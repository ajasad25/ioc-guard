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
from .walk import is_excluded, iter_files

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


def _changed_paths(root: str, base_ref: str) -> List[str]:
    proc = subprocess.run(["git", "-C", root, "diff", "--name-only", base_ref, "HEAD"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError("git diff against %s failed: %s"
                           % (base_ref, proc.stderr.decode("utf-8", "replace").strip()))
    return [p for p in proc.stdout.decode("utf-8", "replace").splitlines() if p]


def _diff_findings(root: str, base_ref: str) -> List[Finding]:
    findings = []
    for path in _changed_paths(root, base_ref):
        if is_excluded(path):
            continue
        head_file = os.path.join(root, path)
        if not os.path.exists(head_file):
            continue
        try:
            with open(head_file, "rb") as fh:
                head = fh.read()
        except OSError:
            continue
        findings.extend(compare_file(path, _git_show(root, base_ref, path), head))
    return findings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="ioc-guard",
                                description="Scan a tree for EtherHiding supply-chain worm indicators (see iocs.txt).")
    p.add_argument("--root", default=".")
    p.add_argument("--iocs", default=str(DEFAULT_IOCS))
    p.add_argument("--base-ref", default=None,
                   help="git ref to diff against; enables .gitignore and CRLF rules")
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

    if args.base_ref and not _require_ref(root, args.base_ref):
        sys.stderr.write(
            "ioc-guard: ERROR: cannot resolve --base-ref %r in %s.\n"
            "  Refusing to report a scan whose diff rules never ran.\n"
            % (args.base_ref, root))
        return EXIT_ERROR

    findings = []
    try:
        for relpath, text in iter_files(root):
            findings.extend(scan_text(text, patterns, relpath))
            findings.extend(run_heuristics(text, relpath))
        if args.base_ref:
            findings.extend(_diff_findings(root, args.base_ref))
    except Exception as exc:
        sys.stderr.write("ioc-guard: ERROR: scan failed: %s\n" % exc)
        return EXIT_ERROR

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

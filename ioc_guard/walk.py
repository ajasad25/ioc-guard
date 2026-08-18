"""Filesystem traversal with the exclusions that prevented false positives before."""
import os
from typing import Iterator, Tuple

EXCLUDED_DIRS = (".git", "node_modules", "dist", "build", ".next",
                 "vendor", "coverage", ".ioc-guard", ".pytest_cache", "__pycache__")
EXCLUDED_SUFFIXES = (".min.js", ".min.css", ".map")
MAX_BYTES = 8 * 1024 * 1024

ENGINE_ROOT = os.path.realpath(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELF_EXEMPT_MARKER = b"ioc-guard" + b":self-exempt"
# The literal above is split so that walk.py's own source does not contain the
# contiguous marker — otherwise this file would exempt itself.

# Only these two engine files may self-exempt. Both necessarily contain
# indicator strings: iocs.txt holds every literal pattern, and heuristics.py
# names child_process/windowsHide in its own rule definitions. An allowlist
# rather than a directory prefix, so that a repository nested inside the
# engine's own checkout can never exempt itself.
SELF_EXEMPT_PATHS = frozenset({
    "iocs.txt",
    os.path.join("ioc_guard", "heuristics.py"),
})


def is_excluded(relpath: str) -> bool:
    parts = relpath.replace(os.sep, "/").split("/")
    if any(p in EXCLUDED_DIRS for p in parts):
        return True
    return relpath.endswith(EXCLUDED_SUFFIXES)


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _is_engine_self_exempt(fullpath, data):
    """True only for one of ioc-guard's own marked files.

    Requires both that the file IS an allowlisted engine file and that it
    carries the marker. The marker alone exempts nothing, anywhere.
    """
    resolved = os.path.realpath(fullpath)
    try:
        rel = os.path.relpath(resolved, ENGINE_ROOT)
    except ValueError:          # different drive on Windows
        return False
    if rel.startswith(os.pardir):
        return False
    if rel not in SELF_EXEMPT_PATHS:
        return False
    return SELF_EXEMPT_MARKER in data[:4096]


def iter_files(root) -> Iterator[Tuple[str, str]]:
    root = str(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if is_excluded(rel):
                continue
            try:
                if os.path.getsize(full) > MAX_BYTES:
                    continue
                with open(full, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            if _is_engine_self_exempt(full, data):
                continue
            if _looks_binary(data):
                continue
            yield rel, data.decode("utf-8", "replace")

"""Filesystem traversal with the exclusions that prevented false positives before."""
import os
from typing import Iterator, Tuple

EXCLUDED_DIRS = (".git", "node_modules", "dist", "build", ".next",
                 "vendor", "coverage", ".ioc-guard", ".pytest_cache", "__pycache__")
EXCLUDED_SUFFIXES = (".min.js", ".min.css", ".map")
MAX_BYTES = 8 * 1024 * 1024

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF_EXEMPT_MARKER = b"ioc-guard" + b":self-exempt"


def is_excluded(relpath: str) -> bool:
    parts = relpath.replace(os.sep, "/").split("/")
    if any(p in EXCLUDED_DIRS for p in parts):
        return True
    return relpath.endswith(EXCLUDED_SUFFIXES)


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _is_engine_self_exempt(fullpath, data):
    """True only for ioc-guard's own files that carry the marker.

    Scoped to the engine's own directory: the marker is inert inside a
    scanned repository, so it cannot be used to evade detection.
    """
    resolved = os.path.abspath(fullpath)
    if resolved != ENGINE_ROOT and not resolved.startswith(ENGINE_ROOT + os.sep):
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

"""Filesystem traversal with the exclusions that prevented false positives before."""
import fnmatch
import os
import stat
from typing import Iterator, Optional, Tuple

# Directories excluded wherever they appear. Dependency trees are deep and
# vendored copies are legitimately nested, so these cannot be anchored.
EXCLUDED_DIRS_ANY_DEPTH = (".git", "node_modules", "vendor",
                           ".pytest_cache", "__pycache__")

# Build output, anchored to the top level only. `build/webpack.config.js` is the
# standard Vue-CLI 2 layout, and an unanchored match turns every one of these
# names into a free hiding place at any depth -- including `src/.ioc-guard/`.
EXCLUDED_DIRS_TOP_LEVEL = ("dist", "build", "coverage", ".next", ".ioc-guard")

# Kept as a union for callers that only ask "is this name a build directory".
EXCLUDED_DIRS = EXCLUDED_DIRS_ANY_DEPTH + EXCLUDED_DIRS_TOP_LEVEL

# Skipped outright: no rule has ever fired usefully on these and they are large.
EXCLUDED_SUFFIXES = (".min.css", ".map")

# Minified bundles are NOT skipped: the literal indicator list still runs on
# them, because repacking a payload into a *.min.js is one edit away. Only the
# length/density heuristics are waived, since a minifier trips those by
# construction.
MINIFIED_SUFFIXES = (".min.js", ".min.cjs", ".min.mjs")

MAX_BYTES = 8 * 1024 * 1024
NUL_WINDOW = 8192

# Names where the file is meant to hold text a build tool reads or executes.
# A NUL byte in one of these is itself an indicator: it costs an attacker two
# bytes to add and, before this, made the whole file invisible to every rule.
SOURCE_SUFFIXES = (".js", ".cjs", ".mjs", ".jsx", ".ts", ".tsx", ".mts", ".cts",
                   ".json", ".yml", ".yaml", ".md", ".sh", ".bash", ".zsh", ".py")

# Generated bundles live here. I7 anchors these to the top level so that a
# nested one is no longer a free hiding place -- but a bundle is still a bundle,
# and it trips the length/density rules by construction. Measured on one local
# checkout: scanning nested web/dist and server/dist produced 35 long-line hits
# and zero true positives. So they are scanned for the literal indicators, which
# is what closes the hiding place, and exempted from the density heuristics --
# exactly the treatment I7 prescribes for *.min.js.
BUILD_OUTPUT_DIRS = ("dist", "build", "coverage", ".next")

# Data and markup formats where a >3000 char line or a run of escapes is
# ordinary: SVG path data, generated HTML reports, prose, lockfiles, snapshots.
# Measured across ten local checkouts, these were the entire false-positive
# population of the length and density heuristics, with zero true positives.
NON_CODE_SUFFIXES = (".svg", ".html", ".htm", ".md", ".json", ".csv",
                     ".lock", ".snap", ".xml", ".txt")

ENGINE_ROOT = os.path.realpath(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELF_EXEMPT_MARKER = b"ioc-guard" + b":self-exempt"
# The literal above is split so that walk.py's own source does not contain the
# contiguous marker — otherwise this file would exempt itself.

# Only these two engine files may self-exempt. Both necessarily contain
# indicator strings: iocs.txt holds every literal pattern, and heuristics.py
# defines the terms used by the hidden-process-spawn heuristic. An allowlist
# rather than a directory prefix, so that a repository nested inside the
# engine's own checkout can never exempt itself.
SELF_EXEMPT_PATHS = frozenset({
    "iocs.txt",
    os.path.join("ioc_guard", "heuristics.py"),
})

# Note for contributors: prose under ioc_guard/ is scanned by
# test_scanner_does_not_flag_its_own_source. A comment, docstring or help
# string that contains the campaign marker, or that names both terms of the
# hidden-spawn heuristic in one file, will fail that test. Reword the prose --
# do not weaken a pattern in iocs.txt and do not add entries here.


class ScanStats(object):
    """What the walk did not look at, so the gap can be reported rather than hidden.

    A silently skipped file is indistinguishable from a clean one, which is
    exactly the property an attacker buys with a single NUL byte or an
    oversized file. Callers pass one of these to `iter_files` and print the
    total; ignoring it keeps the old (relpath, text) iteration contract intact.
    """

    __slots__ = ("binary", "oversize", "unreadable", "special")

    def __init__(self):
        self.binary = 0
        self.oversize = 0
        self.unreadable = 0
        self.special = 0

    @property
    def skipped(self) -> int:
        return self.binary + self.oversize + self.unreadable + self.special


def _norm(relpath: str) -> str:
    return str(relpath).replace(os.sep, "/")


def _basename(relpath: str) -> str:
    return _norm(relpath).rsplit("/", 1)[-1]


def is_excluded(relpath: str) -> bool:
    norm = _norm(relpath)
    dirs = norm.split("/")[:-1]
    if any(d in EXCLUDED_DIRS_ANY_DEPTH for d in dirs):
        return True
    if dirs and dirs[0] in EXCLUDED_DIRS_TOP_LEVEL:
        return True
    return norm.endswith(EXCLUDED_SUFFIXES)


def is_source_like(relpath: str) -> bool:
    """True for names a build tool reads as text, where a NUL is an indicator."""
    base = _basename(relpath).lower()
    if base == ".gitignore":
        return True
    if fnmatch.fnmatch(base, "*.config.*"):
        return True
    return base.endswith(SOURCE_SUFFIXES)


def in_build_output(relpath: str) -> bool:
    """True for a path under a build-output directory at any depth."""
    return any(d in BUILD_OUTPUT_DIRS for d in _norm(relpath).split("/")[:-1])


def allows_density_heuristics(relpath: str) -> bool:
    """True where a >3000 char line or dense \\u00XX escapes are abnormal.

    The spec scoped the length rule to source and build configs; dropping that
    scoping turned inline SVG path data, committed HTML reports and long prose
    lines into a permanently red required check, which is how a control gets
    muted. The literal indicator patterns stay unscoped -- they are precise.
    """
    if in_build_output(relpath):
        return False
    base = _basename(relpath).lower()
    if base.endswith(MINIFIED_SUFFIXES):
        return False
    if base.endswith(NON_CODE_SUFFIXES):
        return False
    if fnmatch.fnmatch(base, "*.config.*"):
        return True
    return base.endswith(SOURCE_SUFFIXES)


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:NUL_WINDOW]


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


def iter_files(root, stats: Optional[ScanStats] = None) -> Iterator[Tuple[str, str]]:
    root = str(root)
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        at_top = os.path.abspath(dirpath) == root_abs
        kept = []
        for d in dirnames:
            if d in EXCLUDED_DIRS_ANY_DEPTH:
                continue
            if at_top and d in EXCLUDED_DIRS_TOP_LEVEL:
                continue
            kept.append(d)
        dirnames[:] = kept
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if is_excluded(rel):
                continue
            try:
                # lstat, not getsize: a symlink into /dev or out of the tree
                # must never be opened, stalled on, or read as repo content.
                st = os.lstat(full)
            except OSError:
                if stats is not None:
                    stats.unreadable += 1
                continue
            if not stat.S_ISREG(st.st_mode):
                if stats is not None:
                    stats.special += 1
                continue
            if st.st_size > MAX_BYTES:
                if stats is not None:
                    stats.oversize += 1
                continue
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
            except OSError:
                if stats is not None:
                    stats.unreadable += 1
                continue
            if _is_engine_self_exempt(full, data):
                continue
            if _looks_binary(data) and not is_source_like(rel):
                if stats is not None:
                    stats.binary += 1
                continue
            # A source-like file carrying a NUL is decoded with replacement and
            # scanned anyway; heuristics.py reports the NUL itself as a finding.
            yield rel, data.decode("utf-8", "replace")

"""Filesystem traversal with the exclusions that prevented false positives before."""
import fnmatch
import os
import stat
from typing import Iterator, Optional, Tuple

# Directories excluded wherever they appear. Dependency trees are deep and
# vendored copies are legitimately nested, so these cannot be anchored.
EXCLUDED_DIRS_ANY_DEPTH = (".git", "node_modules", "vendor",
                           ".pytest_cache", "__pycache__")

# Excluded at the top level only. `.ioc-guard` is where CI checks the engine
# out, so scanning it would be self-detection; nested `src/.ioc-guard/` is a
# hiding place and is still scanned.
#
# Build output (dist, build, coverage, .next) is deliberately NOT here any
# more. Excluding it left the easiest hiding place in the tool: an attacker
# needed no nesting at all, and `build/webpack.base.conf.js` is checked-in
# source in the standard Vue-CLI 2 layout. Those directories are walked and
# matched against the literal indicators like anything else; only the
# length/density heuristics are waived, through DENSITY_WAIVED_DIRS below.
#
# Nothing else has been added here. Committed virtualenvs and generated client
# code are noisy, but noise is a reason to waive a heuristic, not a reason to
# stop looking at a file: a compromised PyPI or npm package lands in exactly
# those trees, and this scanner exists for supply-chain compromise.
EXCLUDED_DIRS_TOP_LEVEL = (".ioc-guard",)

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
SOURCE_SUFFIXES = (
    # JavaScript / TypeScript, and the component formats that compile to it
    ".js", ".cjs", ".mjs", ".jsx", ".ts", ".tsx", ".mts", ".cts",
    ".vue", ".svelte", ".astro", ".mdx",
    # data and config a build tool reads
    ".json", ".yml", ".yaml", ".toml", ".env", ".md",
    # anything a build step executes. The Windows batch file the campaign
    # drops is itself a named indicator in iocs.txt, so a file named after an
    # IOC must not be the one file that gets no structural analysis.
    ".sh", ".bash", ".zsh", ".py", ".bat", ".cmd", ".ps1",
)

# Same intent, for the build files that carry no extension at all.
SOURCE_BASENAMES = ("dockerfile", "makefile", "gnumakefile", "procfile",
                    ".gitignore", ".npmrc", ".babelrc", ".eslintrc")

# Generated and vendored trees, at any depth including the top level. They are
# walked and matched against the literal indicators -- that is what closes the
# hiding place -- but they trip the length/density rules by construction: one
# local checkout produced 35 long-line hits from web/dist and server/dist with
# zero true positives, and a committed virtualenv trips it on generated
# protobuf modules. So only the density heuristics are waived here, exactly the
# treatment *.min.js gets. space-padding, spawn-hidden-window, nul-in-source
# and every literal pattern still run.
#
# venv, .venv, site-packages and generated sit here rather than in
# EXCLUDED_DIRS_ANY_DEPTH on purpose. A committed virtualenv is third-party
# code that can genuinely carry a payload -- a compromised PyPI release lands
# in site-packages, which is the whole shape of this campaign -- and a scanner
# that stops looking there is blind exactly where supply-chain compromise
# arrives. "generated" is also an ordinary English word that a repo may well
# use for hand-written code. Waiving the density rules removes the measured
# noise; excluding the trees would remove the detection with it, and this
# scanner's exclusion list is public now.
DENSITY_WAIVED_DIRS = ("dist", "build", "coverage", ".next",
                       "venv", ".venv", "site-packages", "generated")

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

    __slots__ = ("binary", "oversize", "unreadable", "special", "names")

    # A bare count is not actionable: "skipped 2 file(s)" tells an operator
    # nothing about whether one of them mattered. Names are kept, bounded.
    MAX_NAMED = 20

    def __init__(self):
        self.binary = 0
        self.oversize = 0
        self.unreadable = 0
        self.special = 0
        self.names = []

    def note(self, reason: str, relpath: str) -> None:
        setattr(self, reason, getattr(self, reason) + 1)
        if len(self.names) < ScanStats.MAX_NAMED:
            self.names.append((relpath, reason))

    @property
    def skipped(self) -> int:
        return self.binary + self.oversize + self.unreadable + self.special

    def describe(self):
        """Lines naming what was skipped, source-adjacent names first."""
        order = {"binary": 0, "oversize": 1, "special": 2, "unreadable": 3}
        ranked = sorted(self.names,
                        key=lambda nr: (0 if is_source_like(nr[0]) else 1,
                                        order.get(nr[1], 9), nr[0]))
        label = {"binary": "binary content", "oversize": ">8MB",
                 "special": "not a regular file (symlink, fifo, device)",
                 "unreadable": "unreadable"}
        out = ["  %s (%s)" % (rel, label.get(reason, reason)) for rel, reason in ranked]
        hidden = self.skipped - len(self.names)
        if hidden > 0:
            out.append("  ...and %d more not listed" % hidden)
        return out


def split_lines(text: str):
    """Split on newlines the way git, grep and every editor do: LF only.

    str.splitlines() also breaks on lone CR, form feed, \x0b, \x1c-\x1e,
    \x85, \u2028 and \u2029. That cost us both ways. Line numbers drifted --
    a real .gitignore with 47 lone CRs reported its indicator at line 95 when
    git says 48, sending an operator to the wrong place. And the extra
    separators are an evasion: JavaScript does not treat \x0c or \u2028-in-a-
    string as a statement break, so an attacker could sprinkle them through a
    long payload line, keep it one line for Node, and have every fragment fall
    under the length threshold here. A trailing CR is dropped so CRLF files
    still report clean excerpts and honest lengths.
    """
    return [line[:-1] if line.endswith("\r") else line
            for line in text.split("\n")]


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
    if base in SOURCE_BASENAMES:
        return True
    # .env, .env.local, .env.production ...
    if base == ".env" or base.startswith(".env."):
        return True
    if fnmatch.fnmatch(base, "*.config.*"):
        return True
    return base.endswith(SOURCE_SUFFIXES)


def in_density_waived_tree(relpath: str) -> bool:
    """True for a path under a generated or vendored tree, at any depth."""
    return any(d in DENSITY_WAIVED_DIRS for d in _norm(relpath).split("/")[:-1])


def allows_density_heuristics(relpath: str) -> bool:
    """True where a >3000 char line or dense \\u00XX escapes are abnormal.

    The spec scoped the length rule to source and build configs; dropping that
    scoping turned inline SVG path data, committed HTML reports and long prose
    lines into a permanently red required check, which is how a control gets
    muted. The literal indicator patterns stay unscoped -- they are precise.
    """
    if in_density_waived_tree(relpath):
        return False
    base = _basename(relpath).lower()
    if base.endswith(MINIFIED_SUFFIXES):
        return False
    if base.endswith(NON_CODE_SUFFIXES):
        return False
    if fnmatch.fnmatch(base, "*.config.*"):
        return True
    if base in SOURCE_BASENAMES or base == ".env" or base.startswith(".env."):
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
                    stats.note("unreadable", rel)
                continue
            if not stat.S_ISREG(st.st_mode):
                if stats is not None:
                    stats.note("special", rel)
                continue
            if st.st_size > MAX_BYTES:
                if stats is not None:
                    stats.note("oversize", rel)
                continue
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
            except OSError:
                if stats is not None:
                    stats.note("unreadable", rel)
                continue
            if _is_engine_self_exempt(full, data):
                continue
            if _looks_binary(data) and not is_source_like(rel):
                if stats is not None:
                    stats.note("binary", rel)
                continue
            # A source-like file carrying a NUL is decoded with replacement and
            # scanned anyway; heuristics.py reports the NUL itself as a finding.
            yield rel, data.decode("utf-8", "replace")

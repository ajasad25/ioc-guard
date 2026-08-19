"""Literal indicator matching against the maintained iocs.txt list."""
import re
from typing import List, Pattern, Tuple

from .finding import Finding
from .walk import split_lines

EXCERPT_RADIUS = 60


def load_patterns(path) -> List[Tuple[str, Pattern]]:
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append((line, re.compile(line, re.IGNORECASE)))
    return out


def _excerpt(line: str, start: int, end: int) -> str:
    lo = max(0, start - EXCERPT_RADIUS)
    hi = min(len(line), end + EXCERPT_RADIUS)
    text = line[lo:hi]
    if lo > 0:
        text = "..." + text
    if hi < len(line):
        text = text + "..."
    return text


def scan_text(text: str, patterns, path: str) -> List[Finding]:
    findings = []
    for lineno, line in enumerate(split_lines(text), 1):
        for label, rx in patterns:
            m = rx.search(line)
            if m:
                findings.append(Finding(path=path, line=lineno,
                                        rule="ioc:" + label,
                                        excerpt=_excerpt(line, m.start(), m.end())))
    return findings

"""Structural rules that survive re-obfuscation of the literal indicators."""
# ioc-guard:self-exempt
import re
from typing import List

from .finding import Finding
from .walk import allows_density_heuristics, is_source_like

MAX_LINE_LEN = 3000
MIN_UNICODE_ESCAPES = 40
MIN_PAD_SPACES = 300
NUL = "\x00"

_UNICODE_ESCAPE = re.compile(r"\\u00[0-9a-fA-F]{2}")
_LONG_SPACE_RUN = re.compile(r" {%d,}" % MIN_PAD_SPACES)
_CLOSING_BRACE = re.compile(r"\}\s*;")
_CHILD_PROCESS = re.compile(r"child_process", re.IGNORECASE)
_WINDOWS_HIDE = re.compile(r"windowsHide", re.IGNORECASE)


def _short(line: str) -> str:
    return line[:150] + "..." if len(line) > 150 else line


def run_heuristics(text: str, path: str) -> List[Finding]:
    findings = []
    # The length and density rules are scoped to source and build configs.
    # Unscoped, their only measured hits were SVG path data, generated HTML and
    # long prose lines -- noise that turns the whole check red and gets it muted.
    dense = allows_density_heuristics(path)
    lines = text.splitlines()

    for lineno, line in enumerate(lines, 1):
        if dense and len(line) > MAX_LINE_LEN:
            findings.append(Finding(path=path, line=lineno,
                                    rule="heuristic:long-line",
                                    excerpt="line is %d chars: %s" % (len(line), _short(line))))
        if dense and len(_UNICODE_ESCAPE.findall(line)) >= MIN_UNICODE_ESCAPES:
            findings.append(Finding(path=path, line=lineno,
                                    rule="heuristic:unicode-escape-density",
                                    excerpt=_short(line)))
        if _LONG_SPACE_RUN.search(line) and _CLOSING_BRACE.search(line):
            findings.append(Finding(path=path, line=lineno,
                                    rule="heuristic:space-padding",
                                    excerpt="%d+ consecutive spaces on a line closing an object"
                                            % MIN_PAD_SPACES))

    # A NUL byte in a file a build tool reads as text is not legitimate. It used
    # to make the file binary-looking and therefore invisible to every rule
    # above, which is two bytes of attacker cost for a total bypass.
    if is_source_like(path):
        idx = text.find(NUL)
        if idx >= 0:
            findings.append(Finding(path=path, line=text.count("\n", 0, idx) + 1,
                                    rule="heuristic:nul-in-source",
                                    excerpt="NUL byte at offset %d of a source-like file"
                                            % idx))

    if _CHILD_PROCESS.search(text) and _WINDOWS_HIDE.search(text):
        m = _WINDOWS_HIDE.search(text)
        lineno = text.count("\n", 0, m.start()) + 1
        findings.append(Finding(path=path, line=lineno,
                                rule="heuristic:spawn-hidden-window",
                                excerpt="child_process spawned with windowsHide"))
    return findings

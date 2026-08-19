"""Structural rules that survive re-obfuscation of the literal indicators."""
# ioc-guard:self-exempt
import re
from typing import List

from .finding import Finding
from .walk import allows_density_heuristics, is_source_like, split_lines

MAX_LINE_LEN = 3000
MIN_UNICODE_ESCAPES = 40
MIN_PAD_SPACES = 300
MIN_BUNDLE_SHARE = 0.95
MAX_BUNDLE_OTHER_MEDIAN = 200
MIN_BUNDLE_PUNCT_RATIO = 0.05
NUL = "\x00"

_UNICODE_ESCAPE = re.compile(r"\\u00[0-9a-fA-F]{2}")
# A line that is nothing but an SVG path attribute. Path data is drawn from a
# 30-character alphabet with no quotes, parentheses, braces, semicolons,
# backslashes or dollars, so no JavaScript can be expressed in it -- but a
# single icon routinely runs past 4000 characters inside a React component,
# which is a measured false positive of the length rule in two local repos.
_SVG_PATH_LINE = re.compile(
    r"""^\s*(?:<\s*path\s+)?d\s*=\s*(["'])"""
    r"""[\sMmLlHhVvCcSsQqTtAaZz0-9.,+eE-]*"""
    r"""\1\s*(?:/\s*>)?\s*,?\s*$""")
_LONG_SPACE_RUN = re.compile(r" {%d,}" % MIN_PAD_SPACES)
_CLOSING_BRACE = re.compile(r"\}\s*;")
_JS_PUNCT = re.compile(r"[(){}\[\];,=:]")
_CHILD_PROCESS = re.compile(r"child_process", re.IGNORECASE)
_WINDOWS_HIDE = re.compile(r"windowsHide", re.IGNORECASE)


def _short(line: str) -> str:
    return line[:150] + "..." if len(line) > 150 else line


def _is_minified_bundle(text: str, lines: List[str]) -> bool:
    """True when the oversized line is a shipped bundle, not an injected tail.

    The worm appends its loader to an otherwise normally formatted file, behind
    a long run of spaces, so the file keeps all its ordinary lines and gains one
    huge one. A bundle emitted by webpack or rollup is the opposite shape: it is
    long from its first byte, the oversized line essentially IS the file, and
    nothing is padded.

    Measured against every sample on hand this separates cleanly. The three
    quarantined payloads and the live prop-capitals-com infection each carry a
    padding run and put at most 0.898 of their bytes on the long line; the two
    false positives -- a Chart.js 4.5.0 copy and a Superposition UMD bundle,
    61 branches between them -- have no padding and score 0.999 and 1.0.

    Only the length rule consults this. Padding, escape density, hidden-window
    spawn and every literal indicator still apply, so a loader concealed inside
    a genuine bundle is still caught.
    """
    big = [l for l in lines if len(l) > MAX_LINE_LEN]
    if not big:
        return False
    if any(_LONG_SPACE_RUN.search(l) for l in big):
        return False
    # Minified JavaScript is dense with structural punctuation. Requiring it
    # keeps the exemption from covering any file that merely happens to be one
    # very long line, which is a shape with no legitimate build-tool meaning.
    joined = "".join(big)
    if len(_JS_PUNCT.findall(joined)) < MIN_BUNDLE_PUNCT_RATIO * len(joined):
        return False
    if sum(len(l) for l in big) < MIN_BUNDLE_SHARE * max(len(text), 1):
        return False
    others = sorted(len(l) for l in lines if len(l) <= MAX_LINE_LEN and l.strip())
    if not others:
        return True
    return others[len(others) // 2] < MAX_BUNDLE_OTHER_MEDIAN


def run_heuristics(text: str, path: str) -> List[Finding]:
    findings = []
    # The length and density rules are scoped to source and build configs.
    # Unscoped, their only measured hits were SVG path data, generated HTML and
    # long prose lines -- noise that turns the whole check red and gets it muted.
    dense = allows_density_heuristics(path)
    lines = split_lines(text)
    bundle = _is_minified_bundle(text, lines)

    for lineno, line in enumerate(lines, 1):
        if (dense and len(line) > MAX_LINE_LEN
                and not _SVG_PATH_LINE.match(line) and not bundle):
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

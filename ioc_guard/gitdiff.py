"""Rules that need the base revision of a file to see the damage."""
import re
from typing import List

from .finding import Finding

MIN_LINES_FOR_CRLF_RULE = 50
CRLF_FLIP_RATIO = 0.9
_ENV_RULE = re.compile(rb"^\s*!?\**\.env", re.MULTILINE)


def _crlf_ratio(data: bytes) -> float:
    total = data.count(b"\n")
    if total == 0:
        return 0.0
    return data.count(b"\r\n") / float(total)


def compare_file(path: str, base: bytes, head: bytes) -> List[Finding]:
    findings = []

    if path.endswith(".gitignore") and base:
        if _ENV_RULE.search(base) and not _ENV_RULE.search(head):
            findings.append(Finding(path=path, line=0,
                                    rule="diff:gitignore-lost-env",
                                    excerpt=".env rule present in base, absent in head"))

    if base and head and head.count(b"\n") >= MIN_LINES_FOR_CRLF_RULE:
        before, after = _crlf_ratio(base), _crlf_ratio(head)
        if before < 0.1 and after > CRLF_FLIP_RATIO:
            findings.append(Finding(path=path, line=0,
                                    rule="diff:crlf-flip",
                                    excerpt="file converted wholesale to CRLF (%.0f%% -> %.0f%%)"
                                            % (before * 100, after * 100)))
    return findings

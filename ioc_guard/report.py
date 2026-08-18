"""Render findings for humans, for GitHub job summaries, and for machines."""
import json
from dataclasses import asdict
from typing import List

from .finding import Finding

# GitHub rejects or truncates a $GITHUB_STEP_SUMMARY over 1 MiB. One local repo
# produced 6584 findings, which at ~250 bytes a row is ~1.6 MB -- the summary
# would have been lost entirely. The JSON artifact still carries every finding.
MAX_MARKDOWN_ROWS = 200


def render_text(findings: List[Finding]) -> str:
    if not findings:
        return "ioc-guard: clean — no indicators found.\n"
    lines = ["ioc-guard: %d finding(s)\n" % len(findings)]
    lines.extend(f.format() for f in findings)
    return "\n".join(lines) + "\n"


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_markdown(findings: List[Finding]) -> str:
    if not findings:
        return "## ioc-guard\n\nClean — no indicators found.\n"
    rows = ["## ioc-guard\n",
            "**%d finding(s).** This branch must not be merged until they are resolved.\n"
            % len(findings),
            "| File | Line | Rule | Detail |",
            "|---|---|---|---|"]
    for f in findings[:MAX_MARKDOWN_ROWS]:
        rows.append("| `%s` | %d | `%s` | %s |"
                    % (_md_escape(f.path), f.line, _md_escape(f.rule),
                       _md_escape(f.excerpt)[:200]))
    extra = len(findings) - MAX_MARKDOWN_ROWS
    if extra > 0:
        rows.append("")
        rows.append("_…and %d more — see the uploaded ioc-report.json artifact._" % extra)
    return "\n".join(rows) + "\n"


def render_json(findings: List[Finding]) -> str:
    return json.dumps({"count": len(findings),
                       "findings": [asdict(f) for f in findings]}, indent=2)

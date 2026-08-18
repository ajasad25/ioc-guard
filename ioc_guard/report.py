"""Render findings for humans, for GitHub job summaries, and for machines."""
import json
from dataclasses import asdict
from typing import List

from .finding import Finding


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
    for f in findings:
        rows.append("| `%s` | %d | `%s` | %s |"
                    % (_md_escape(f.path), f.line, _md_escape(f.rule),
                       _md_escape(f.excerpt)[:200]))
    return "\n".join(rows) + "\n"


def render_json(findings: List[Finding]) -> str:
    return json.dumps({"count": len(findings),
                       "findings": [asdict(f) for f in findings]}, indent=2)

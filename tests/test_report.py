import json
import re

from ioc_guard.finding import Finding
from ioc_guard.report import render_json, render_markdown, render_text

F = [
    Finding(path="eslint.config.js", line=1, rule="ioc:A9-1800-1", excerpt="global.i=..."),
    Finding(path="eslint.config.js", line=1, rule="heuristic:long-line", excerpt="9000 chars"),
]


def test_text_report_lists_every_finding():
    out = render_text(F)
    assert "eslint.config.js:1: [ioc:A9-1800-1]" in out
    assert "heuristic:long-line" in out


def test_text_report_for_clean_scan_says_so():
    assert "clean" in render_text([]).lower()


def test_markdown_report_is_a_table_with_a_row_per_finding():
    out = render_markdown(F)
    assert out.count("\n|") >= 3
    assert "ioc:A9-1800-1" in out


def test_markdown_report_for_clean_scan_has_no_table():
    assert "|" not in render_markdown([])


def test_json_report_round_trips():
    data = json.loads(render_json(F))
    assert data["count"] == 2
    assert data["findings"][0]["rule"] == "ioc:A9-1800-1"
    assert data["findings"][0]["path"] == "eslint.config.js"


def test_json_report_for_clean_scan_has_zero_count():
    assert json.loads(render_json([]))["count"] == 0


def test_markdown_escapes_pipes_in_every_cell():
    # path can legally contain "|"; rule is a raw regex from iocs.txt where "|"
    # is alternation; excerpt is arbitrary scanned file content.
    hostile = [Finding(path="we|rd.js", line=3, rule="ioc:foo|bar",
                       excerpt="payload | with pipe")]
    row = [l for l in render_markdown(hostile).splitlines()
           if l.startswith("|") and "ioc:" in l][0]
    # 4 delimiters for a 4-column row, and nothing else unescaped
    assert len(re.findall(r"(?<!\\)\|", row)) == 5, row
    assert "we\\|rd.js" in row
    assert "ioc:foo\\|bar" in row


def test_markdown_table_is_capped_and_says_how_many_are_missing():
    # GitHub drops a $GITHUB_STEP_SUMMARY over 1 MiB; 6584 findings would be ~1.6 MB.
    from ioc_guard.report import MAX_MARKDOWN_ROWS

    many = [Finding(path="src/f%d.js" % i, line=i, rule="ioc:A9-1800-1", excerpt="x" * 200)
            for i in range(MAX_MARKDOWN_ROWS + 84)]
    out = render_markdown(many)
    assert out.count("\n| `src/") == MAX_MARKDOWN_ROWS
    assert "…and 84 more" in out
    assert "ioc-report.json" in out
    assert "**%d finding(s).**" % len(many) in out, "the true total must still be stated"
    assert len(out.encode("utf-8")) < 1024 * 1024


def test_a_short_report_has_no_truncation_notice():
    assert "and 0 more" not in render_markdown(F)
    assert "…and" not in render_markdown(F)


def test_json_report_keeps_every_finding_even_when_markdown_is_capped():
    import json as _json

    from ioc_guard.report import MAX_MARKDOWN_ROWS
    many = [Finding(path="f%d.js" % i, line=1, rule="ioc:x", excerpt="e")
            for i in range(MAX_MARKDOWN_ROWS + 10)]
    assert _json.loads(render_json(many))["count"] == MAX_MARKDOWN_ROWS + 10

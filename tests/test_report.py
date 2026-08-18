import json

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

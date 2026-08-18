from ioc_guard.finding import Finding


def test_format_renders_path_line_rule_and_excerpt():
    f = Finding(path="eslint.config.js", line=1, rule="ioc:A9-1800-1",
                excerpt='global.i="A9-1800-1"')
    assert f.format() == 'eslint.config.js:1: [ioc:A9-1800-1] global.i="A9-1800-1"'


def test_findings_are_hashable_so_duplicates_can_be_deduped():
    a = Finding(path="a.js", line=2, rule="heuristic:long-line", excerpt="x")
    b = Finding(path="a.js", line=2, rule="heuristic:long-line", excerpt="x")
    assert len({a, b}) == 1

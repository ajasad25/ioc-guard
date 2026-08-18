from ioc_guard.heuristics import run_heuristics


def rules(findings):
    return sorted({f.rule for f in findings})


def test_long_single_line_is_flagged():
    found = run_heuristics("var a=1;\n" + "z" * 3500 + "\n", "vite.config.js")
    assert "heuristic:long-line" in rules(found)
    assert found[0].line == 2


def test_ordinary_code_is_not_flagged():
    body = "module.exports = {\n  plugins: [require('tailwindcss')],\n};\n"
    assert run_heuristics(body, "tailwind.config.js") == []


def test_dense_unicode_escapes_are_flagged():
    body = "var s='" + "\\u0061" * 45 + "';"
    assert "heuristic:unicode-escape-density" in rules(run_heuristics(body, "a.js"))


def test_a_few_unicode_escapes_are_not_flagged():
    body = "var s='\\u00e9\\u00e8\\u00ea';"
    assert run_heuristics(body, "a.js") == []


def test_child_process_with_hidden_window_is_flagged():
    body = "const cp=require('child_process');\ncp.spawn(x,y,{windowsHide:true});\n"
    assert "heuristic:spawn-hidden-window" in rules(run_heuristics(body, "a.js"))


def test_child_process_alone_is_not_flagged():
    body = "const cp=require('child_process');\ncp.spawn('ls');\n"
    assert run_heuristics(body, "a.js") == []


def test_space_padding_on_the_closing_line_is_flagged():
    body = "module.exports = {\n  a: 1,\n}" + " " * 507 + ";\n"
    assert "heuristic:space-padding" in rules(run_heuristics(body, "postcss.config.js"))


def test_normal_trailing_whitespace_is_not_flagged():
    body = "module.exports = {\n  a: 1,\n};   \n"
    assert run_heuristics(body, "postcss.config.js") == []


def test_long_line_excerpt_is_truncated():
    found = run_heuristics("q" * 9000, "a.js")
    assert len(found[0].excerpt) < 200

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


# --- I1: the length/density rules are scoped to source and build configs ---

SVG_PATH = 'd="M36.78' + '0.5 1.2 3.4 5.6 ' * 400 + 'z"'


def test_long_line_does_not_fire_on_an_svg_path():
    body = "<svg><path %s /></svg>\n" % SVG_PATH
    assert len(SVG_PATH) > 3000
    assert run_heuristics(body, "src/assets/react.svg") == []


def test_long_line_does_not_fire_on_a_long_markdown_line():
    body = "Some prose. " + "word " * 900 + "\n"
    assert len(body) > 3000
    assert run_heuristics(body, "CLAUDE.md") == []


def test_long_line_does_not_fire_on_a_committed_html_report():
    assert run_heuristics("<div>%s</div>" % ("x" * 5000), "playwright-report/index.html") == []


def test_long_line_does_not_fire_on_a_lockfile_or_snapshot():
    assert run_heuristics("x" * 5000, "yarn.lock") == []
    assert run_heuristics("x" * 5000, "__snapshots__/App.test.js.snap") == []
    assert run_heuristics("x" * 5000, "package-lock.json") == []


def test_long_line_still_fires_on_a_js_file():
    assert "heuristic:long-line" in rules(run_heuristics("x" * 5000, "src/index.js"))


def test_long_line_still_fires_on_a_build_config():
    for cfg in ("eslint.config.js", "tailwind.config.js", "vite.config.ts",
                "postcss.config.cjs"):
        assert "heuristic:long-line" in rules(run_heuristics("x" * 5000, cfg)), cfg


def test_unicode_escape_density_does_not_fire_on_an_svg_or_json():
    body = "var s='" + "\\u0061" * 60 + "';"
    assert run_heuristics(body, "icons.svg") == []
    assert run_heuristics(body, "data/blob.json") == []


def test_unicode_escape_density_still_fires_on_a_config():
    body = "var s='" + "\\u0061" * 60 + "';"
    assert "heuristic:unicode-escape-density" in rules(run_heuristics(body, "eslint.config.js"))


def test_minified_bundles_are_exempt_from_the_density_rules():
    assert run_heuristics("x" * 9000, "public/jquery.min.js") == []


# --- C3: a NUL byte in a source-like file is itself a finding ---

def test_nul_in_a_source_file_is_reported():
    body = "/*\x00*/\nmodule.exports={};\n"
    assert "heuristic:nul-in-source" in rules(run_heuristics(body, "eslint.config.js"))


def test_nul_line_number_points_at_the_nul():
    body = "a\nb\nc\x00d\n"
    found = [f for f in run_heuristics(body, "app.js") if f.rule == "heuristic:nul-in-source"]
    assert found and found[0].line == 3


def test_nul_in_a_non_source_name_is_not_reported_by_this_rule():
    assert run_heuristics("\x00", "logo.png") == []


def test_clean_source_has_no_nul_finding():
    assert run_heuristics("module.exports={};\n", "app.js") == []


# --- the other two heuristics stay unscoped: they are precise, not noisy ---

def test_space_padding_is_not_scoped_away():
    body = "module.exports = {\n  a: 1,\n}" + " " * 507 + ";\n"
    assert "heuristic:space-padding" in rules(run_heuristics(body, "weird.txt"))


def test_spawn_hidden_window_is_not_scoped_away():
    body = "const cp=require('child_process');\ncp.spawn(x,y,{windowsHide:true});\n"
    assert "heuristic:spawn-hidden-window" in rules(run_heuristics(body, "notes.md"))

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


# --- I1, measured: the two remaining false-positive shapes ---

SVG_ATTR = 'd="M36.785 11.97h14.173v2.597h-5.572' + "h-.5v.2l1.2-3.4 2.5 0 0 1 " * 300 + '.5z"'


def test_long_line_does_not_fire_on_an_svg_path_inside_a_component():
    # Measured in two local repos: a Trustpilot logo path, 4693 chars, inside
    # a .jsx. Path data has no quotes, parens, braces, semicolons, backslashes
    # or dollars, so no JavaScript can be expressed in it.
    line = "                " + SVG_ATTR
    assert len(line) > 3000
    assert run_heuristics(line + "\n", "src/components/TrustpilotSection.jsx") == []
    assert run_heuristics("  <path " + SVG_ATTR + " />\n", "src/Icon.tsx") == []


def test_long_line_still_fires_on_a_long_line_that_is_not_path_data():
    body = 'const x = "%s";' % ("A" * 4000)
    assert "heuristic:long-line" in rules(run_heuristics(body, "src/Icon.jsx"))


def test_a_payload_line_is_not_mistaken_for_path_data():
    body = 'd="M36.785";global.r=require;%s' % ("x" * 4000)
    assert "heuristic:long-line" in rules(run_heuristics(body, "src/Icon.jsx"))


def test_density_heuristics_are_off_inside_committed_build_output():
    # I7 anchors dist/ to the top level so a nested one is scanned -- but a
    # bundle still trips the length rule by construction. 35 hits, no true
    # positives, in one local checkout.
    for p in ("web/dist/assets/Dashboard-abc.js", "server/dist/services/x.js",
              "packages/ui/build/index.js", "app/.next/static/chunk.js"):
        assert run_heuristics("import{a as b}" + "x" * 9000, p) == [], p


# --- residual 2: the heuristics reached almost nothing outside .js/.ts ---

PAYLOAD_SHAPE = "var s='" + "\\u0061" * 60 + "';" + "x" * 4000


def test_the_structural_heuristics_reach_the_widened_allowlist():
    # Verified failing before: an identical payload in App.vue, config.bat,
    # Dockerfile and tool.ps1 fired on x.js only.
    for name in ("src/App.vue", "config.bat", "Dockerfile", "tool.ps1",
                 "src/Widget.svelte", "pages/index.astro", "x.js",
                 "pyproject.toml", ".env", "docker/Dockerfile", "Makefile"):
        got = rules(run_heuristics(PAYLOAD_SHAPE, name))
        assert "heuristic:long-line" in got, name
        assert "heuristic:unicode-escape-density" in got, name


def test_a_nul_in_the_widened_allowlist_is_reported():
    for name in ("src/App.vue", "config.bat", "Dockerfile", "tool.ps1", ".env"):
        assert "heuristic:nul-in-source" in rules(run_heuristics("a\x00b", name)), name


def test_build_output_keeps_the_precise_rules_and_loses_only_density():
    body = "module.exports = {\n  a: 1,\n}" + " " * 507 + ";\n"
    assert "heuristic:space-padding" in rules(run_heuristics(body, "build/webpack.base.conf.js"))
    spawn = "const cp=require('child_process');\ncp.spawn(x,y,{windowsHide:true});\n"
    assert "heuristic:spawn-hidden-window" in rules(run_heuristics(spawn, "dist/main.js"))
    assert "heuristic:nul-in-source" in rules(run_heuristics("a\x00b", "build/webpack.base.conf.js"))
    assert run_heuristics("x" * 9000, "build/webpack.base.conf.js") == []

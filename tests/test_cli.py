import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent


def run(args, cwd=None):
    return subprocess.run([sys.executable, "-m", "ioc_guard"] + args,
                          cwd=str(cwd or REPO), capture_output=True, text=True)


def test_clean_tree_exits_zero(tmp_path):
    (tmp_path / "app.js").write_text("module.exports = {};\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "clean" in r.stdout.lower()


def test_infected_tree_exits_one(tmp_path):
    (tmp_path / "eslint.config.js").write_text('global.i="A9-1800-1";\n')
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1
    assert "A9-1800-1" in r.stdout


def test_missing_ioc_file_exits_two_not_zero(tmp_path):
    r = run(["--root", str(tmp_path), "--iocs", str(tmp_path / "nope.txt")])
    assert r.returncode == 2, "a broken scanner must not look like a clean scan"


def test_json_report_is_written(tmp_path):
    (tmp_path / "a.js").write_text("helloipbot\n")
    out = tmp_path / "report.json"
    r = run(["--root", str(tmp_path), "--json", str(out)])
    assert r.returncode == 1
    assert json.loads(out.read_text())["count"] >= 1


def test_summary_file_is_appended(tmp_path):
    (tmp_path / "a.js").write_text("helloipbot\n")
    summary = tmp_path / "summary.md"
    run(["--root", str(tmp_path), "--summary", str(summary)])
    assert "ioc-guard" in summary.read_text()


def test_scanner_does_not_flag_its_own_source():
    r = run(["--root", str(REPO / "ioc_guard")])
    assert r.returncode == 0, "ioc-guard must not detect itself:\n" + r.stdout


def test_base_ref_that_cannot_be_resolved_exits_two(tmp_path):
    (tmp_path / "a.js").write_text("module.exports={};\n")
    r = run(["--root", str(tmp_path), "--base-ref", "no-such-ref"])
    assert r.returncode == 2, "a base-ref that resolves to nothing must not look clean"
    assert "clean" not in r.stdout.lower()


def test_base_ref_in_a_non_git_directory_exits_two(tmp_path):
    (tmp_path / "a.js").write_text("module.exports={};\n")
    r = run(["--root", str(tmp_path), "--base-ref", "main"])
    assert r.returncode == 2


def test_base_ref_happy_path_runs_the_diff_rules(tmp_path):
    import subprocess as sp

    def git(*a):
        sp.run(["git", "-C", str(tmp_path)] + list(a), check=True,
               stdout=sp.DEVNULL, stderr=sp.DEVNULL)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("node_modules\n.env\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = sp.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                  capture_output=True, text=True).stdout.strip()
    (tmp_path / ".gitignore").write_text("node_modules\n")   # the worm's edit
    git("add", "-A")
    git("commit", "-q", "-m", "strip env rule")

    r = run(["--root", str(tmp_path), "--base-ref", base])
    assert r.returncode == 1
    assert "gitignore-lost-env" in r.stdout


def test_unwritable_summary_destination_exits_two(tmp_path):
    (tmp_path / "a.js").write_text("module.exports={};\n")
    r = run(["--root", str(tmp_path), "--summary", str(tmp_path / "nope" / "s.md")])
    assert r.returncode == 2
    assert "clean" not in r.stdout.lower(), "a write failure must not print a clean result"


def test_unwritable_json_destination_exits_two(tmp_path):
    (tmp_path / "a.js").write_text("module.exports={};\n")
    r = run(["--root", str(tmp_path), "--json", str(tmp_path / "nope" / "r.json")])
    assert r.returncode == 2


def test_quiet_suppresses_the_text_report(tmp_path):
    (tmp_path / "bad.js").write_text('global.i="A9-1800-1";\n')
    r = run(["--root", str(tmp_path), "--quiet"])
    assert r.returncode == 1
    assert r.stdout.strip() == ""


def test_infected_fixture_is_detected():
    r = run(["--root", str(REPO / "tests" / "fixtures" / "infected")])
    assert r.returncode == 1
    assert "A9-1800-1" in r.stdout


def test_clean_fixture_passes():
    r = run(["--root", str(REPO / "tests" / "fixtures" / "clean")])
    assert r.returncode == 0, r.stdout


def test_a_nul_byte_no_longer_hides_a_payload(tmp_path):
    # C3 regression, exactly as reproduced: two extra bytes used to turn
    # "1 finding" into "clean — no indicators found." with no skipped line.
    (tmp_path / "eslint.config.js").write_bytes(
        b'/*\x00*/\nmodule.exports={};\nglobal.i="A9-1800-1";\n')
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "A9-1800-1" in r.stdout
    assert "heuristic:nul-in-source" in r.stdout


def test_skipped_files_are_reported_rather_than_hidden(tmp_path):
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    (tmp_path / "a.js").write_text("module.exports={};\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 0
    assert "skipped 1 file(s)" in r.stderr, r.stderr


def test_nothing_skipped_prints_no_skipped_line(tmp_path):
    (tmp_path / "a.js").write_text("module.exports={};\n")
    r = run(["--root", str(tmp_path)])
    assert "skipped" not in r.stderr


def test_a_payload_below_a_nested_build_directory_is_scanned(tmp_path):
    # I7 regression: `build` matched at any depth, so this was skipped silently.
    nested = tmp_path / "packages" / "app" / "build"
    nested.mkdir(parents=True)
    (nested / "webpack.config.js").write_text('global.i="A9-1800-1";\n')
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "webpack.config.js" in r.stdout


def test_a_payload_repacked_into_a_minified_bundle_is_still_caught(tmp_path):
    # I7 regression: *.min.js was skipped entirely.
    (tmp_path / "payload.min.js").write_text("!function(){}();global.i=\"A9-1800-1\";\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr


def test_an_svg_and_a_long_readme_do_not_fail_a_clean_repo(tmp_path):
    # I1 regression: these produced a permanently red required check.
    (tmp_path / "logo.svg").write_text('<svg><path d="M36.78%s"/></svg>\n' % ("1.5 2.5 " * 500))
    (tmp_path / "CLAUDE.md").write_text("prose " * 900 + "\n")
    (tmp_path / "index.html").write_text("<div>%s</div>\n" % ("x" * 6000))
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr


# --- base-ref diff rules: I2 (quoted paths) and I4 (deletions) ---

def make_git_repo(tmp_path):
    import subprocess as sp

    def git(*a):
        sp.run(["git", "-C", str(tmp_path)] + list(a), check=True,
               stdout=sp.DEVNULL, stderr=sp.DEVNULL)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    # the default this bug lived under; set explicitly so the test is not at
    # the mercy of the machine's global git config
    git("config", "core.quotePath", "true")
    return git


def head_of(tmp_path):
    import subprocess as sp
    return sp.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
                  capture_output=True, text=True).stdout.strip()


def test_a_c_quoted_unicode_path_is_seen_by_the_diff_rules(tmp_path):
    # I2 regression: without -z git returns "caf\303\251.js", which matched no
    # real path, so a wholesale CRLF flip of that file produced no finding.
    git = make_git_repo(tmp_path)
    body = "\n".join("line %d" % i for i in range(200)) + "\n"
    (tmp_path / "café.js").write_text(body, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = head_of(tmp_path)
    (tmp_path / "café.js").write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
    git("add", "-A")
    git("commit", "-q", "-m", "crlf flip")

    r = run(["--root", str(tmp_path), "--base-ref", base])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "diff:crlf-flip" in r.stdout


def test_deleting_gitignore_entirely_is_flagged(tmp_path):
    # I4 regression: the path is listed by the diff but absent from the head
    # tree, and was skipped -- so deleting the file scored better than editing it.
    git = make_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules\n.env\n")
    (tmp_path / "a.js").write_text("module.exports={};\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = head_of(tmp_path)
    (tmp_path / ".gitignore").unlink()
    git("add", "-A")
    git("commit", "-q", "-m", "delete gitignore")

    r = run(["--root", str(tmp_path), "--base-ref", base])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "diff:gitignore-lost-env" in r.stdout


def test_head_ref_lets_the_diff_rules_run_against_a_ref_that_is_not_head(tmp_path):
    git = make_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".env\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = head_of(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules\n")
    git("add", "-A")
    git("commit", "-q", "-m", "strip env")
    tip = head_of(tmp_path)
    git("checkout", "-q", base)          # detach: HEAD is no longer the tip

    r = run(["--root", str(tmp_path), "--base-ref", base, "--head-ref", tip])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "diff:gitignore-lost-env" in r.stdout


def test_diff_only_skips_the_tree_walk(tmp_path):
    git = make_git_repo(tmp_path)
    (tmp_path / "a.js").write_text("module.exports={};\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = head_of(tmp_path)
    # untracked payload in the working tree: the tree walk would flag it,
    # the diff pass must not look at it at all
    (tmp_path / "local-notes.js").write_text('global.i="A9-1800-1";\n')

    assert run(["--root", str(tmp_path)]).returncode == 1
    r = run(["--root", str(tmp_path), "--base-ref", base, "--diff-only"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_diff_only_without_base_ref_is_an_operational_error(tmp_path):
    r = run(["--root", str(tmp_path), "--diff-only"])
    assert r.returncode == 2


def test_unresolvable_head_ref_exits_two(tmp_path):
    git = make_git_repo(tmp_path)
    (tmp_path / "a.js").write_text("module.exports={};\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = head_of(tmp_path)
    r = run(["--root", str(tmp_path), "--base-ref", base, "--head-ref", "no-such-ref"])
    assert r.returncode == 2
    assert "clean" not in r.stdout.lower()


def test_a_payload_in_nested_build_output_is_still_caught_by_the_literals(tmp_path):
    # The density heuristics are waived there; the literal indicators are not.
    out = tmp_path / "web" / "dist" / "assets"
    out.mkdir(parents=True)
    (out / "index-abc123.js").write_text('import{a as b};global.i="A9-1800-1";\n')
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "A9-1800-1" in r.stdout


def test_a_committed_bundle_alone_does_not_fail_the_check(tmp_path):
    out = tmp_path / "web" / "dist" / "assets"
    out.mkdir(parents=True)
    (out / "index-abc123.js").write_text("import{$n as e,Gn as t}" + "x" * 90000 + "\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr


# --- residuals from the scoped re-review ---

def test_a_payload_in_top_level_build_is_caught(tmp_path):
    # Reproduction: this reported "clean", exit 0, with no skipped-file line.
    build = tmp_path / "build"
    build.mkdir()
    (build / "webpack.base.conf.js").write_text(
        'global.i="A9-1800-1";\n'
        "global['r']=require;\n"
        "const cp=require('child_process');\n"
        "cp.spawn(x,y,{windowsHide:true});\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "A9-1800-1" in r.stdout
    assert "heuristic:spawn-hidden-window" in r.stdout


def test_a_payload_in_top_level_dist_or_next_is_caught(tmp_path):
    for d in ("dist", ".next", "coverage"):
        sub = tmp_path / d
        sub.mkdir()
        (sub / "chunk.js").write_text('global.i="A9-1800-1";\n')
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    for d in ("dist", ".next", "coverage"):
        assert "%s/chunk.js" % d in r.stdout


def test_a_committed_top_level_bundle_alone_is_still_not_noise(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index-abc.js").write_text("import{$n as e,Gn as t}" + "x" * 90000 + "\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_config_bat_and_a_vue_component_get_the_structural_heuristics(tmp_path):
    body = "var s='" + "\\u0061" * 60 + "';" + "x" * 4000
    (tmp_path / "config.bat").write_text(body)
    (tmp_path / "App.vue").write_text(body)
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    for name in ("config.bat", "App.vue"):
        assert "%s:1: [heuristic:long-line]" % name in r.stdout, r.stdout
        assert "%s:1: [heuristic:unicode-escape-density]" % name in r.stdout


def test_a_nul_no_longer_hides_a_payload_in_a_vue_file_or_config_bat(tmp_path):
    (tmp_path / "Widget.vue").write_bytes(b'<script>\x00</script>\nglobal.i="A9-1800-1";\n')
    (tmp_path / "config.bat").write_bytes(b'@echo off\x00\nrem A9-1800-1\n')
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Widget.vue" in r.stdout and "config.bat" in r.stdout
    assert r.stdout.count("heuristic:nul-in-source") == 2


def test_the_skipped_line_names_the_files(tmp_path):
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    (tmp_path / "a.js").write_text("module.exports={};\n")
    r = run(["--root", str(tmp_path)])
    assert "skipped 1 file(s)" in r.stderr
    assert "logo.png" in r.stderr, r.stderr


# --- FP2/FP3: committed virtualenvs and generated client code ---

def test_a_committed_virtualenv_produces_no_findings(tmp_path):
    sp = (tmp_path / "backend" / "venv" / "lib" / "python3.12"
          / "site-packages" / "google" / "protobuf")
    sp.mkdir(parents=True)
    (sp / "descriptor_pb2.py").write_text(
        '_sym_db = 1\n"inlineSchema": "%s"\n' % ("A" * 19160))
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_committed_generated_client_code_produces_no_findings(tmp_path):
    gen = tmp_path / "generated" / "prisma"
    gen.mkdir(parents=True)
    (gen / "edge.js").write_text('  "inlineSchema": "generator %s"\n' % ("c" * 15629))
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_payload_inside_a_committed_virtualenv_is_still_caught(tmp_path):
    # The point of waiving density rather than excluding: a compromised PyPI
    # release lands here, and that is the shape of this whole campaign.
    sp = tmp_path / "venv" / "lib" / "python3.12" / "site-packages" / "evil"
    sp.mkdir(parents=True)
    (sp / "hook.py").write_text('MARKER = "A9-1800-1"\n')
    (sp / "postinstall.js").write_text("global['!']='9-1800';\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "A9-1800-1" in r.stdout
    assert "hook.py" in r.stdout and "postinstall.js" in r.stdout


def test_a_payload_inside_generated_client_code_is_still_caught(tmp_path):
    gen = tmp_path / "generated" / "prisma"
    gen.mkdir(parents=True)
    (gen / "edge.js").write_text(
        'const cp=require("child_process");\n'
        "cp.spawn(x,y,{windowsHide:true});\n"
        'global.i="A9-1800-1";\n')
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "A9-1800-1" in r.stdout
    assert "heuristic:spawn-hidden-window" in r.stdout


def test_a_nul_inside_a_vendored_tree_is_still_reported(tmp_path):
    sp = tmp_path / ".venv" / "lib" / "site-packages"
    sp.mkdir(parents=True)
    (sp / "mod.py").write_bytes(b"import os\x00\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "heuristic:nul-in-source" in r.stdout


def test_the_gitignore_artifact_still_fires(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules\ndist\nconfig.bat\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ioc:config" in r.stdout


def test_config_batch_in_source_no_longer_fires(tmp_path):
    (tmp_path / "main.rs").write_text('    let status = if config.batch {\n')
    (tmp_path / "SKILL.md").write_text("Set config.batch to true.\n")
    r = run(["--root", str(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr

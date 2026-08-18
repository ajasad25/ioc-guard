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

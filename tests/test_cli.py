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

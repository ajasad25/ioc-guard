"""The reusable workflow's shell is executed here with stubbed git/python3.

GitHub Actions cannot be run locally, so this exercises the one part that can
be: the shell script inside the `run:` block, under the same `bash -e {0}`
invocation GitHub uses, with the ${{ }} values supplied as environment
variables exactly as the workflow supplies them.
"""
import os
import pathlib
import subprocess

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "scan.yml"


def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def scan_step():
    steps = workflow()["jobs"]["scan"]["steps"]
    return [s for s in steps if s.get("name") == "Scan"][0]


def test_workflow_is_valid_yaml_with_the_expected_shape():
    wf = workflow()
    assert "workflow_call" in wf[True] or "workflow_call" in wf.get("on", {})
    assert wf["jobs"]["scan"]["permissions"] == {"contents": "read"}


def test_no_expression_is_interpolated_into_any_run_block():
    # C1: `${{ github.base_ref }}` inside a run: block is arbitrary code
    # execution for anyone who can name a branch.
    for step in workflow()["jobs"]["scan"]["steps"]:
        assert "${{" not in step.get("run", ""), step.get("name")


def test_every_expression_value_reaches_the_shell_through_env():
    env = scan_step()["env"]
    for key in ("BASE_REF", "EVENT_NAME", "EVENT_BEFORE", "WORKSPACE", "RUNNER_TEMP"):
        assert key in env, key
    assert env["BASE_REF"] == "${{ github.base_ref }}"
    assert env["EVENT_BEFORE"] == "${{ github.event.before }}"


def _harness(tmp_path, stub_rc=0, rev_parse_rc=0, fetch_rc=0):
    """Write the run: script plus stub git/python3 onto a temp PATH."""
    script = tmp_path / "step.sh"
    script.write_text(scan_step()["run"])
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argfile = tmp_path / "args.txt"

    (bindir / "python3").write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "%s"\nexit %d\n' % ("%s", argfile, stub_rc))
    (bindir / "git").write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  fetch) printf 'FETCH %%s\\n' \"$*\" >> '%s'; exit %d ;;\n"
        "  rev-parse) exit %d ;;\n"
        "esac\n"
        "exit 0\n" % (tmp_path / "git.log", fetch_rc, rev_parse_rc))
    for f in ("python3", "git"):
        os.chmod(str(bindir / f), 0o755)
    return script, bindir, argfile


def run_step(tmp_path, env_overrides, **kw):
    script, bindir, argfile = _harness(tmp_path, **kw)
    env = {
        "PATH": "%s:%s" % (bindir, os.environ.get("PATH", "")),
        "HOME": str(tmp_path),
        "PYTHONPATH": "/ws/.ioc-guard",
        "BASE_REF": "",
        "EVENT_NAME": "",
        "EVENT_BEFORE": "",
        "WORKSPACE": "/ws",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }
    env.update(env_overrides)
    # `bash -e {0}` is exactly how GitHub invokes a run: block.
    proc = subprocess.run(["bash", "-e", str(script)], env=env,
                          capture_output=True, text=True, cwd=str(tmp_path))
    args = argfile.read_text().splitlines() if argfile.exists() else []
    return proc, args


def test_clean_scan_exits_zero(tmp_path):
    proc, args = run_step(tmp_path, {"EVENT_NAME": "push"}, stub_rc=0)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "--root" in args and "/ws" in args


def test_findings_exit_one_and_are_annotated(tmp_path):
    proc, _ = run_step(tmp_path, {"EVENT_NAME": "push"}, stub_rc=1)
    assert proc.returncode == 1
    assert "::error::" in proc.stdout
    assert "Do not merge" in proc.stdout


def test_scanner_error_exits_two_and_is_never_called_clean(tmp_path):
    proc, _ = run_step(tmp_path, {"EVENT_NAME": "push"}, stub_rc=2)
    assert proc.returncode == 2
    assert "NOT a clean result" in proc.stdout
    assert "ioc-guard: clean" not in proc.stdout


def test_an_unexpected_exit_code_is_still_a_failure(tmp_path):
    proc, _ = run_step(tmp_path, {"EVENT_NAME": "push"}, stub_rc=7)
    assert proc.returncode == 7
    assert "NOT a clean result" in proc.stdout


# --- C1: a hostile branch name must not execute ---

HOSTILE = [
    "main`touch %s`",
    "main$(touch %s)",
    "main;touch %s",
    "main|touch %s",
    "main&touch %s",
]


@pytest.mark.parametrize("template", HOSTILE)
def test_a_hostile_base_branch_name_executes_nothing(tmp_path, template):
    marker = tmp_path / "pwned"
    proc, args = run_step(tmp_path,
                          {"EVENT_NAME": "pull_request",
                           "BASE_REF": template % marker},
                          stub_rc=0)
    assert not marker.exists(), "branch name was executed as shell:\n" + proc.stdout
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # the name still reaches the scanner intact, as one argv element
    assert "--base-ref" in args
    assert args[args.index("--base-ref") + 1] == "origin/" + (template % marker)


# --- I3: the diff rules must run on push, not only on pull_request ---

def test_push_passes_the_previous_tip_as_base_ref(tmp_path):
    before = "a" * 40
    _, args = run_step(tmp_path, {"EVENT_NAME": "push", "EVENT_BEFORE": before})
    assert "--base-ref" in args
    assert args[args.index("--base-ref") + 1] == before


def test_push_of_a_new_branch_passes_no_base_ref(tmp_path):
    _, args = run_step(tmp_path, {"EVENT_NAME": "push", "EVENT_BEFORE": "0" * 40})
    assert "--base-ref" not in args


def test_push_with_an_unresolvable_previous_tip_warns_and_skips(tmp_path):
    before = "b" * 40
    proc, args = run_step(tmp_path,
                          {"EVENT_NAME": "push", "EVENT_BEFORE": before},
                          rev_parse_rc=1)
    assert "--base-ref" not in args
    assert "::warning::" in proc.stdout
    assert proc.returncode == 0


def test_schedule_run_passes_no_base_ref(tmp_path):
    _, args = run_step(tmp_path, {"EVENT_NAME": "schedule"})
    assert "--base-ref" not in args


def test_pull_request_fetches_the_base_branch(tmp_path):
    proc, args = run_step(tmp_path, {"EVENT_NAME": "pull_request", "BASE_REF": "main"})
    assert args[args.index("--base-ref") + 1] == "origin/main"
    assert "FETCH" in (tmp_path / "git.log").read_text()


def test_a_failed_base_branch_fetch_is_an_error_not_a_clean_scan(tmp_path):
    proc, _ = run_step(tmp_path,
                       {"EVENT_NAME": "pull_request", "BASE_REF": "main"},
                       fetch_rc=1)
    assert proc.returncode == 2
    assert "ioc-guard: clean" not in proc.stdout

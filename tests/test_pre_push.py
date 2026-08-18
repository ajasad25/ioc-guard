import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
HOOK = REPO / "hooks" / "pre-push"
ZERO = "0" * 40


def git(cwd, *args, **kw):
    return subprocess.run(["git"] + list(args), cwd=str(cwd),
                          capture_output=True, text=True, **kw)


def make_repo(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "t@example.com")
    git(d, "config", "user.name", "t")
    return d


def commit(d, filename, body):
    (d / filename).write_text(body)
    git(d, "add", filename)
    git(d, "commit", "-q", "-m", "c")
    return git(d, "rev-parse", "HEAD").stdout.strip()


def run_hook(repo, stdin, env=None):
    e = dict(os.environ)
    e["IOC_GUARD_ENGINE"] = str(REPO)
    e["IOC_GUARD_PYTHON"] = sys.executable
    e.update(env or {})
    return subprocess.run(["bash", str(HOOK), "origin", "https://example.com/r.git"],
                          cwd=str(repo), input=stdin, capture_output=True, text=True, env=e)


def test_fast_forward_push_of_clean_code_is_allowed(tmp_path):
    d = make_repo(tmp_path, "clean")
    first = commit(d, "a.js", "module.exports={};\n")
    second = commit(d, "b.js", "console.log(1);\n")
    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (second, first))
    assert r.returncode == 0, r.stdout + r.stderr


def test_non_fast_forward_push_is_blocked(tmp_path):
    d = make_repo(tmp_path, "force")
    first = commit(d, "a.js", "module.exports={};\n")
    git(d, "commit", "-q", "--amend", "-m", "rewritten")
    rewritten = git(d, "rev-parse", "HEAD").stdout.strip()
    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (rewritten, first))
    assert r.returncode != 0
    assert "non-fast-forward" in (r.stdout + r.stderr).lower()


def test_branch_deletion_is_blocked(tmp_path):
    d = make_repo(tmp_path, "del")
    sha = commit(d, "a.js", "x\n")
    r = run_hook(d, "(delete) %s refs/heads/main %s\n" % (ZERO, sha))
    assert r.returncode != 0
    assert "deletion" in (r.stdout + r.stderr).lower()


def test_push_containing_an_indicator_is_blocked(tmp_path):
    d = make_repo(tmp_path, "infected")
    first = commit(d, "a.js", "module.exports={};\n")
    second = commit(d, "eslint.config.js", 'global.i="A9-1800-1";\n')
    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (second, first))
    assert r.returncode != 0
    assert "A9-1800-1" in (r.stdout + r.stderr)


def test_override_allows_a_blocked_push_and_is_logged(tmp_path):
    d = make_repo(tmp_path, "override")
    first = commit(d, "a.js", "module.exports={};\n")
    git(d, "commit", "-q", "--amend", "-m", "rewritten")
    rewritten = git(d, "rev-parse", "HEAD").stdout.strip()
    log = tmp_path / "override.log"
    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (rewritten, first),
                 env={"IOC_GUARD": "off", "IOC_GUARD_LOG": str(log)})
    assert r.returncode == 0
    assert "override" in log.read_text().lower()


def test_new_branch_with_no_remote_counterpart_is_scanned_not_rejected(tmp_path):
    d = make_repo(tmp_path, "newbranch")
    sha = commit(d, "a.js", "module.exports={};\n")
    r = run_hook(d, "refs/heads/feat %s refs/heads/feat %s\n" % (sha, ZERO))
    assert r.returncode == 0, r.stdout + r.stderr

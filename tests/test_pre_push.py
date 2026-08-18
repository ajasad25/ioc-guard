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


def test_a_unicode_filename_cannot_smuggle_an_indicator(tmp_path):
    # Regression: git C-quotes non-ASCII paths without -z, which previously made
    # the archive step match nothing and the scan report clean.
    d = make_repo(tmp_path, "unicode")
    first = commit(d, "a.js", "module.exports={};\n")
    second = commit(d, "café.js", 'global.i="A9-1800-1";\n')
    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (second, first))
    assert r.returncode != 0, "a rename must not defeat the hook:\n" + r.stdout + r.stderr


def test_a_filename_with_a_space_is_still_scanned(tmp_path):
    d = make_repo(tmp_path, "space")
    first = commit(d, "a.js", "module.exports={};\n")
    second = commit(d, "my config.js", 'global.i="A9-1800-1";\n')
    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (second, first))
    assert r.returncode != 0


def test_a_filename_with_a_quote_is_still_scanned(tmp_path):
    d = make_repo(tmp_path, "quote")
    first = commit(d, "a.js", "module.exports={};\n")
    second = commit(d, 'we"rd.js', 'global.i="A9-1800-1";\n')
    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (second, first))
    assert r.returncode != 0


def test_override_log_records_the_ref_and_shas(tmp_path):
    d = make_repo(tmp_path, "overridelog")
    first = commit(d, "a.js", "module.exports={};\n")
    git(d, "commit", "-q", "--amend", "-m", "rewritten")
    rewritten = git(d, "rev-parse", "HEAD").stdout.strip()
    log = tmp_path / "override.log"
    run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (rewritten, first),
             env={"IOC_GUARD": "off", "IOC_GUARD_LOG": str(log)})
    text = log.read_text()
    assert "refs/heads/main" in text
    assert rewritten in text


def remove(d, filename):
    git(d, "rm", "-q", filename)
    git(d, "commit", "-q", "-m", "remove")
    return git(d, "rev-parse", "HEAD").stdout.strip()


# --- I8: a payload that erases itself before the tip must still be caught ---

def test_a_payload_in_an_intermediate_commit_is_caught(tmp_path):
    # INCIDENT-REPORT.md: the payload "rewrote itself out of the working tree
    # after running, to hide". A tip-only scan reported this clean.
    d = make_repo(tmp_path, "selferase")
    first = commit(d, "a.js", "module.exports={};\n")
    commit(d, "eslint.config.js", 'global.i="A9-1800-1";\n')
    tip = remove(d, "eslint.config.js")

    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (tip, first))
    assert r.returncode != 0, "a self-erasing payload must not pass:\n" + r.stdout + r.stderr
    assert "A9-1800-1" in (r.stdout + r.stderr)


def test_a_payload_edited_out_again_is_caught(tmp_path):
    d = make_repo(tmp_path, "editedout")
    first = commit(d, "eslint.config.js", "module.exports={};\n")
    commit(d, "eslint.config.js", 'module.exports={};\nglobal.i="A9-1800-1";\n')
    tip = commit(d, "eslint.config.js", "module.exports={};\n")

    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (tip, first))
    assert r.returncode != 0, r.stdout + r.stderr


def test_a_clean_multi_commit_range_is_still_allowed(tmp_path):
    d = make_repo(tmp_path, "multiclean")
    first = commit(d, "a.js", "module.exports={};\n")
    commit(d, "b.js", "console.log(1);\n")
    commit(d, "c.js", "console.log(2);\n")
    tip = commit(d, "d.js", "console.log(3);\n")
    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (tip, first))
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_long_range_is_capped_and_the_truncation_is_announced(tmp_path):
    d = make_repo(tmp_path, "capped")
    first = commit(d, "a.js", "module.exports={};\n")
    for i in range(4):
        commit(d, "f%d.js" % i, "console.log(%d);\n" % i)
    tip = git(d, "rev-parse", "HEAD").stdout.strip()

    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (tip, first),
                 env={"IOC_GUARD_MAX_COMMITS": "2"})
    out = r.stdout + r.stderr
    assert "WARNING" in out and "NOT scanned" in out, out
    assert "4 commits" in out, out
    assert r.returncode == 0, out


def test_a_merge_commit_range_is_scanned(tmp_path):
    d = make_repo(tmp_path, "merge")
    first = commit(d, "a.js", "module.exports={};\n")
    git(d, "checkout", "-q", "-b", "side")
    commit(d, "eslint.config.js", 'global.i="A9-1800-1";\n')
    git(d, "checkout", "-q", "main")
    commit(d, "b.js", "console.log(1);\n")
    git(d, "merge", "-q", "--no-ff", "-m", "merge", "side")
    tip = git(d, "rev-parse", "HEAD").stdout.strip()

    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (tip, first))
    assert r.returncode != 0, r.stdout + r.stderr


# --- I6: publishing an indicator update must not need the nuclear override ---

def test_skip_scan_allows_an_indicator_update_through(tmp_path):
    d = make_repo(tmp_path, "iocupdate")
    first = commit(d, "a.js", "module.exports={};\n")
    second = commit(d, "iocs.txt", "A9-1800-1\nhelloipbot\n")

    blocked = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (second, first))
    assert blocked.returncode != 0, "sanity: this is blocked without the flag"

    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (second, first),
                 env={"IOC_GUARD_SKIP_SCAN": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "content scan skipped" in (r.stdout + r.stderr)


def test_skip_scan_still_blocks_a_force_push(tmp_path):
    d = make_repo(tmp_path, "skipforce")
    first = commit(d, "a.js", "module.exports={};\n")
    git(d, "commit", "-q", "--amend", "-m", "rewritten")
    rewritten = git(d, "rev-parse", "HEAD").stdout.strip()
    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (rewritten, first),
                 env={"IOC_GUARD_SKIP_SCAN": "1"})
    assert r.returncode != 0, "skipping the scan must not disable the force-push block"
    assert "non-fast-forward" in (r.stdout + r.stderr).lower()


def test_skip_scan_still_blocks_a_branch_deletion(tmp_path):
    d = make_repo(tmp_path, "skipdel")
    sha = commit(d, "a.js", "x\n")
    r = run_hook(d, "(delete) %s refs/heads/main %s\n" % (ZERO, sha),
                 env={"IOC_GUARD_SKIP_SCAN": "1"})
    assert r.returncode != 0
    assert "deletion" in (r.stdout + r.stderr).lower()


# --- I3: the rules aimed at the incident's real damage now run in the hook ---

def test_stripping_the_env_rule_from_gitignore_is_blocked(tmp_path):
    d = make_repo(tmp_path, "envrule")
    (d / ".gitignore").write_text("node_modules\n.env\n")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "base")
    first = git(d, "rev-parse", "HEAD").stdout.strip()
    (d / ".gitignore").write_text("node_modules\n")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "strip env rule")
    tip = git(d, "rev-parse", "HEAD").stdout.strip()

    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (tip, first))
    assert r.returncode != 0, r.stdout + r.stderr
    assert "gitignore-lost-env" in (r.stdout + r.stderr)


def test_deleting_gitignore_is_blocked_by_the_hook(tmp_path):
    d = make_repo(tmp_path, "envdelete")
    (d / ".gitignore").write_text("node_modules\n.env\n")
    (d / "a.js").write_text("module.exports={};\n")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "base")
    first = git(d, "rev-parse", "HEAD").stdout.strip()
    git(d, "rm", "-q", ".gitignore")
    git(d, "commit", "-q", "-m", "drop gitignore")
    tip = git(d, "rev-parse", "HEAD").stdout.strip()

    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (tip, first))
    assert r.returncode != 0, r.stdout + r.stderr
    assert "gitignore-lost-env" in (r.stdout + r.stderr)


def test_a_wholesale_crlf_flip_is_blocked(tmp_path):
    d = make_repo(tmp_path, "crlf")
    body = "\n".join("line %d" % i for i in range(200)) + "\n"
    (d / "app.js").write_text(body)
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "base")
    first = git(d, "rev-parse", "HEAD").stdout.strip()
    (d / "app.js").write_bytes(body.replace("\n", "\r\n").encode())
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "crlf")
    tip = git(d, "rev-parse", "HEAD").stdout.strip()

    r = run_hook(d, "refs/heads/main %s refs/heads/main %s\n" % (tip, first))
    assert r.returncode != 0, r.stdout + r.stderr
    assert "crlf-flip" in (r.stdout + r.stderr)


def test_a_missing_engine_is_an_operational_error_not_a_block(tmp_path):
    d = make_repo(tmp_path, "noengine")
    sha = commit(d, "a.js", "module.exports={};\n")
    r = run_hook(d, "refs/heads/feat %s refs/heads/feat %s\n" % (sha, ZERO),
                 env={"IOC_GUARD_ENGINE": str(tmp_path / "nowhere")})
    assert r.returncode == 2, "a broken install must not look like findings or a pass"

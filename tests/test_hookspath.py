"""C2: a repo-local core.hooksPath silently defeats the global hook.

These exercise the detection script and the chaining helper directly. They
never run hooks/install.sh, and never touch any repository outside tmp_path.
"""
import os
import pathlib
import stat
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent
SCAN = REPO / "hooks" / "scan-hookspath.sh"
CHAIN = REPO / "hooks" / "chain-into-local.sh"
INSTALL = REPO / "hooks" / "install.sh"


def git(cwd, *args):
    return subprocess.run(["git"] + list(args), cwd=str(cwd),
                          capture_output=True, text=True)


def make_repo(parent, name, hookspath=None):
    d = parent / name
    d.mkdir(parents=True)
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "t@example.com")
    git(d, "config", "user.name", "t")
    if hookspath:
        git(d, "config", "--local", "core.hooksPath", hookspath)
    return d


def run(script, *args, **kw):
    env = dict(os.environ)
    env.update(kw.pop("env", {}))
    return subprocess.run(["bash", str(script)] + list(args),
                          capture_output=True, text=True, env=env, **kw)


# --- detection ---

def test_a_repo_with_a_local_hookspath_is_reported(tmp_path):
    make_repo(tmp_path, "plain")
    make_repo(tmp_path, "husky-repo", ".husky/_")
    make_repo(tmp_path, "githooks-repo", ".githooks")

    r = run(SCAN, str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    out = r.stdout + r.stderr
    assert "husky-repo" in out
    assert "githooks-repo" in out
    assert "plain" not in out


def test_both_remedies_are_named(tmp_path):
    make_repo(tmp_path, "githooks-repo", ".githooks")
    out = run(SCAN, str(tmp_path)).stderr
    assert "chain-into-local.sh" in out
    assert "--unset core.hooksPath" in out


def test_a_clean_tree_reports_no_collision(tmp_path):
    make_repo(tmp_path, "plain")
    r = run(SCAN, str(tmp_path))
    assert r.returncode == 0
    assert "no repository sets its own" in r.stdout


def test_a_repo_already_pointing_at_our_hooks_dir_is_not_reported(tmp_path):
    dest = tmp_path / "hooksdir"
    make_repo(tmp_path, "ours", str(dest))
    r = run(SCAN, str(tmp_path), env={"IOC_GUARD_HOOKS_DIR": str(dest)})
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_scan_changes_no_repository_configuration(tmp_path):
    d = make_repo(tmp_path, "githooks-repo", ".githooks")
    before = git(d, "config", "--local", "--list").stdout
    run(SCAN, str(tmp_path))
    assert git(d, "config", "--local", "--list").stdout == before


def test_install_sh_exposes_the_scan_without_installing_anything(tmp_path):
    # --scan-repos must not touch git config; assert by reading the script,
    # since running install.sh for real would set a GLOBAL core.hooksPath.
    src = INSTALL.read_text()
    scan_branch = src.split('if [ "${1:-}" = "--scan-repos" ]; then', 1)[1].split("fi", 1)[0]
    assert "exec" in scan_branch and "scan-hookspath.sh" in scan_branch
    assert "git config --global" not in scan_branch
    # ...and the normal install path runs the report too
    assert src.index("git config --global core.hooksPath") < src.index(
        'IOC_GUARD_HOOKS_DIR="$DEST" "$SRC/hooks/scan-hookspath.sh"')


def test_install_sh_removes_the_engine_before_copying_it(tmp_path):
    src = INSTALL.read_text()
    assert src.index('rm -rf "$ENGINE/ioc_guard"') < src.index('cp -R "$SRC/ioc_guard"')


# --- chaining ---

def chained_hook(d, hookspath=".githooks"):
    return d / hookspath / "pre-push"


def test_chaining_creates_a_hook_when_none_exists(tmp_path):
    d = make_repo(tmp_path, "githooks-repo", ".githooks")
    r = run(CHAIN, str(d))
    assert r.returncode == 0, r.stdout + r.stderr
    target = chained_hook(d)
    assert target.exists()
    assert ">>> ioc-guard" in target.read_text()
    assert os.stat(str(target)).st_mode & stat.S_IXUSR


def test_chaining_preserves_an_existing_hook_and_runs_first(tmp_path):
    d = make_repo(tmp_path, "githooks-repo", ".githooks")
    (d / ".githooks").mkdir()
    target = chained_hook(d)
    target.write_text("#!/usr/bin/env bash\nnpm test\n")
    os.chmod(str(target), 0o755)

    assert run(CHAIN, str(d)).returncode == 0
    text = target.read_text()
    assert "npm test" in text
    assert text.splitlines()[0] == "#!/usr/bin/env bash"
    assert text.index(">>> ioc-guard") < text.index("npm test"), \
        "ioc-guard must run before a hook that may consume stdin"


def test_chaining_is_idempotent(tmp_path):
    d = make_repo(tmp_path, "githooks-repo", ".githooks")
    run(CHAIN, str(d))
    once = chained_hook(d).read_text()
    r = run(CHAIN, str(d))
    assert r.returncode == 0
    assert chained_hook(d).read_text() == once
    assert "already chained" in r.stdout


def test_chaining_handles_a_hook_with_no_shebang(tmp_path):
    d = make_repo(tmp_path, "husky-style", ".githooks")
    (d / ".githooks").mkdir()
    chained_hook(d).write_text("npm run lint\n")
    assert run(CHAIN, str(d)).returncode == 0
    text = chained_hook(d).read_text()
    assert text.index(">>> ioc-guard") < text.index("npm run lint")


def test_chaining_refuses_a_non_shell_hook(tmp_path):
    d = make_repo(tmp_path, "pyhook", ".githooks")
    (d / ".githooks").mkdir()
    chained_hook(d).write_text("#!/usr/bin/env python3\nprint('hi')\n")
    r = run(CHAIN, str(d))
    assert r.returncode == 2
    assert "not a shell script" in r.stderr
    assert "print('hi')" in chained_hook(d).read_text(), "the hook must be left alone"


def test_chaining_redirects_husky_generated_dir_to_the_owned_one(tmp_path):
    d = make_repo(tmp_path, "husky-repo", ".husky/_")
    assert run(CHAIN, str(d)).returncode == 0
    assert (d / ".husky" / "pre-push").exists(), \
        "husky regenerates .husky/_, so the block must go in the file it dispatches to"
    assert not (d / ".husky" / "_" / "pre-push").exists()


def test_chaining_a_repo_without_a_local_hookspath_is_an_error(tmp_path):
    d = make_repo(tmp_path, "plain")
    r = run(CHAIN, str(d))
    assert r.returncode == 2
    assert "no repo-local core.hooksPath" in r.stderr


def test_the_chained_block_runs_ioc_guard_and_passes_stdin_on(tmp_path):
    d = make_repo(tmp_path, "githooks-repo", ".githooks")
    (d / ".githooks").mkdir()
    target = chained_hook(d)
    # the repo's own hook reads the ref list from stdin, like git's sample does
    target.write_text("#!/usr/bin/env bash\ncat > own-stdin.txt\n")
    os.chmod(str(target), 0o755)
    assert run(CHAIN, str(d)).returncode == 0

    fake_hooks = tmp_path / "global-hooks"
    fake_hooks.mkdir()
    (fake_hooks / "pre-push").write_text(
        "#!/usr/bin/env bash\ncat > '%s'\nexit 0\n" % (d / "ioc-stdin.txt"))
    os.chmod(str(fake_hooks / "pre-push"), 0o755)

    refs = "refs/heads/main abc refs/heads/main def\n"
    proc = subprocess.run(["bash", str(target), "origin", "https://example.com/r.git"],
                          cwd=str(d), input=refs, capture_output=True, text=True,
                          env=dict(os.environ, IOC_GUARD_HOOKS_DIR=str(fake_hooks)))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (d / "ioc-stdin.txt").read_text() == refs, "ioc-guard must receive the ref list"
    assert (d / "own-stdin.txt").read_text() == refs, "the repo's own hook must still get it"


def test_the_chained_block_propagates_a_block(tmp_path):
    d = make_repo(tmp_path, "githooks-repo", ".githooks")
    assert run(CHAIN, str(d)).returncode == 0
    target = chained_hook(d)

    fake_hooks = tmp_path / "global-hooks"
    fake_hooks.mkdir()
    (fake_hooks / "pre-push").write_text("#!/usr/bin/env bash\ncat >/dev/null\nexit 1\n")
    os.chmod(str(fake_hooks / "pre-push"), 0o755)

    proc = subprocess.run(["bash", str(target)], cwd=str(d),
                          input="refs/heads/main a refs/heads/main b\n",
                          capture_output=True, text=True,
                          env=dict(os.environ, IOC_GUARD_HOOKS_DIR=str(fake_hooks)))
    assert proc.returncode == 1, "a blocked push must not fall through to the repo's hook"

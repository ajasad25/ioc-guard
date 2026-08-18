from ioc_guard.walk import (ScanStats, allows_density_heuristics, is_excluded,
                            is_source_like, iter_files)


def test_excludes_dependency_and_build_directories():
    assert is_excluded("node_modules/foo/index.js")
    assert is_excluded("dist/bundle.js")
    assert is_excluded(".next/server/page.js")
    assert is_excluded("build/output.js")
    assert is_excluded("coverage/lcov-report/index.js")
    assert is_excluded(".git/config")
    assert is_excluded(".ioc-guard/iocs.txt")


def test_dependency_directories_are_excluded_at_any_depth():
    assert is_excluded("packages/app/node_modules/foo/index.js")
    assert is_excluded("third_party/vendor/x.js")
    assert is_excluded("a/b/.git/config")


def test_build_directory_exclusions_are_anchored_to_the_top_level():
    # I7 regression: an unanchored match made these free hiding places at
    # every depth. build/webpack.config.js is the stock Vue-CLI 2 layout, and
    # a monorepo puts one under every package.
    assert not is_excluded("packages/app/build/webpack.config.js")
    assert not is_excluded("frontend/build/webpack.config.js")
    assert not is_excluded("app/.next/server/page.js")
    assert not is_excluded("src/dist/helper.js")
    assert not is_excluded("packages/ui/coverage/report.js")
    assert not is_excluded("src/.ioc-guard/anything.js")


def test_minified_bundles_are_scanned_for_literals_not_skipped():
    # I7 regression: skipping *.min.js entirely let a repacked payload through.
    assert not is_excluded("public/jquery.min.js")
    assert not is_excluded("payload.min.js")
    # ...but the length/density heuristics are waived there, since a minifier
    # trips them by construction.
    assert not allows_density_heuristics("public/jquery.min.js")


def test_source_maps_and_minified_css_are_still_skipped():
    assert is_excluded("public/app.min.css")
    assert is_excluded("public/bundle.js.map")


def test_does_not_exclude_ordinary_source():
    assert not is_excluded("src/index.js")
    assert not is_excluded("eslint.config.js")
    assert not is_excluded("src/distribute/helper.js")


def test_iter_files_yields_text_and_skips_binary(tmp_path):
    (tmp_path / "a.js").write_text("hello")
    (tmp_path / "b.png").write_bytes(b"\x89PNG\x00\x00binary")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "c.js").write_text("dep")

    got = dict(iter_files(tmp_path))
    assert got == {"a.js": "hello"}


def test_iter_files_survives_undecodable_bytes(tmp_path):
    (tmp_path / "weird.js").write_bytes(b"var a = '\xff\xfe';")
    got = dict(iter_files(tmp_path))
    assert "weird.js" in got


def test_engine_files_carrying_the_marker_are_skipped():
    import pathlib

    import ioc_guard

    engine = pathlib.Path(ioc_guard.__file__).resolve().parent.parent
    got = dict(iter_files(engine))
    assert "ioc_guard/heuristics.py" not in got
    assert "iocs.txt" not in got
    assert "ioc_guard/walk.py" in got, "files without the marker must still be scanned"


def test_the_marker_does_not_exempt_a_file_in_a_scanned_repo(tmp_path):
    # An attacker must not be able to evade the scanner by pasting the marker.
    marker = "ioc-guard" + ":self-exempt"      # split so this file is not itself marked
    (tmp_path / "evil.js").write_text(
        "// %s\nglobal.i='A9-1800-1';\n" % marker)
    got = dict(iter_files(tmp_path))
    assert "evil.js" in got, "the marker is inert outside the engine's allowlist"


def test_a_repo_nested_inside_the_engine_cannot_self_exempt():
    # The evasion path: a scanned repo living under the engine's own checkout.
    import pathlib
    import shutil

    import ioc_guard

    engine = pathlib.Path(ioc_guard.__file__).resolve().parent.parent
    nested = engine / "_nested_target_fixture"
    nested.mkdir(exist_ok=True)
    try:
        marker = "ioc-guard" + ":self-exempt"
        (nested / "evil.js").write_text("// %s\nglobal.i='A9-1800-1';\n" % marker)
        got = dict(iter_files(nested))
        assert "evil.js" in got, "a nested repo must never inherit the engine's exemption"
    finally:
        shutil.rmtree(nested)


def test_test_files_are_not_self_exempted():
    import pathlib

    import ioc_guard

    engine = pathlib.Path(ioc_guard.__file__).resolve().parent.parent
    got = dict(iter_files(engine))
    assert "tests/test_walk.py" in got, "only allowlisted engine files may self-exempt"


def test_an_unlisted_engine_file_with_the_marker_is_still_scanned(tmp_path, monkeypatch):
    # Belt and braces: the marker alone must not be sufficient, even inside the engine.
    import ioc_guard.walk as walk

    monkeypatch.setattr(walk, "ENGINE_ROOT", str(tmp_path))
    marker = "ioc-guard" + ":self-exempt"
    (tmp_path / "not_allowlisted.py").write_text("# %s\n" % marker)
    got = dict(walk.iter_files(tmp_path))
    assert "not_allowlisted.py" in got


def test_density_heuristics_are_scoped_to_source_and_build_configs():
    # I1: these fired on inline SVG path data, generated HTML and prose.
    for noisy in ("src/logo.svg", "playwright-report/index.html", "CLAUDE.md",
                  "package-lock.json", "data/rows.csv", "yarn.lock",
                  "__snapshots__/App.test.js.snap"):
        assert not allows_density_heuristics(noisy), noisy
    for code in ("src/index.js", "eslint.config.js", "tailwind.config.js",
                 "src/app.tsx", "scripts/load.mjs", "tools/run.py"):
        assert allows_density_heuristics(code), code


def test_source_like_covers_the_files_a_build_tool_reads():
    assert is_source_like("eslint.config.js")
    assert is_source_like("README.md")
    assert is_source_like(".gitignore")
    assert is_source_like("deploy/.gitignore")
    assert is_source_like("vite.config.ts")
    assert not is_source_like("logo.png")
    assert not is_source_like("fonts/x.woff2")


def test_a_nul_byte_does_not_hide_a_source_file_from_the_walk(tmp_path):
    # C3 regression: one NUL made the file look binary, so it was skipped
    # silently and every rule -- literals included -- stopped seeing it.
    (tmp_path / "eslint.config.js").write_bytes(
        b'/*\x00*/\nmodule.exports={};\nglobal.i="A9-1800-1";\n')
    got = dict(iter_files(tmp_path))
    assert "eslint.config.js" in got
    assert "A9-1800-1" in got["eslint.config.js"]


def test_a_nul_in_a_real_binary_is_still_skipped_and_counted(tmp_path):
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    stats = ScanStats()
    got = dict(iter_files(tmp_path, stats))
    assert got == {}
    assert stats.binary == 1
    assert stats.skipped == 1


def test_oversize_files_are_counted_rather_than_silently_dropped(tmp_path):
    import ioc_guard.walk as walk

    big = tmp_path / "big.js"
    big.write_bytes(b"x" * (walk.MAX_BYTES + 1))
    stats = ScanStats()
    assert dict(iter_files(tmp_path, stats)) == {}
    assert stats.oversize == 1


def test_symlinks_are_not_followed(tmp_path):
    import os

    (tmp_path / "real.js").write_text("module.exports={};\n")
    os.symlink(str(tmp_path / "real.js"), str(tmp_path / "link.js"))
    os.symlink("/nowhere/at/all.js", str(tmp_path / "dangling.js"))
    stats = ScanStats()
    got = dict(iter_files(tmp_path, stats))
    assert set(got) == {"real.js"}, "a symlink must never be opened as repo content"
    assert stats.special == 2


def test_iter_files_without_stats_keeps_the_old_two_tuple_contract(tmp_path):
    (tmp_path / "a.js").write_text("hello")
    assert dict(iter_files(tmp_path)) == {"a.js": "hello"}

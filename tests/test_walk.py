from ioc_guard.walk import is_excluded, iter_files


def test_excludes_dependency_and_build_directories():
    assert is_excluded("node_modules/foo/index.js")
    assert is_excluded("dist/bundle.js")
    assert is_excluded("app/.next/server/page.js")
    assert is_excluded(".git/config")
    assert is_excluded(".ioc-guard/iocs.txt")


def test_excludes_minified_files():
    assert is_excluded("public/jquery.min.js")


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
    (tmp_path / "evil.js").write_text(
        "// ioc-guard:self-exempt\nglobal.i='A9-1800-1';\n")
    got = dict(iter_files(tmp_path))
    assert "evil.js" in got, "the marker is inert outside the engine's own directory"

import pathlib

from ioc_guard.patterns import load_patterns, scan_text

IOCS = pathlib.Path(__file__).resolve().parent.parent / "iocs.txt"


def test_load_skips_comments_and_blank_lines():
    pats = load_patterns(IOCS)
    labels = [label for label, _ in pats]
    assert "A9-1800-1" in labels
    assert not any(l.startswith("#") for l in labels)
    assert "" not in labels


def test_detects_campaign_marker():
    pats = load_patterns(IOCS)
    found = scan_text('global.i="A9-1800-1";', pats, "eslint.config.js")
    # this line trips two patterns by design -- the marker and the loader shape
    assert "ioc:A9-1800-1" in [f.rule for f in found]
    assert all(f.line == 1 for f in found)


def test_matching_is_case_insensitive():
    pats = load_patterns(IOCS)
    assert scan_text("ETH_GETBLOCKBYNUMBER", pats, "a.js")


def test_bare_hex_wallet_matches_even_though_payload_hides_the_0x_form():
    pats = load_patterns(IOCS)
    body = "var w='\\u0030\\u0078a322E5f3D311D3080e6f0121063e9aDC2490Ef1a'"
    found = scan_text(body, pats, "a.js")
    assert any("a322e5f3" in f.rule for f in found)


def test_excerpt_is_windowed_not_the_whole_line():
    pats = load_patterns(IOCS)
    line = "x" * 5000 + "A9-1800-1" + "y" * 5000
    found = scan_text(line, pats, "big.js")
    assert len(found[0].excerpt) < 200
    assert "A9-1800-1" in found[0].excerpt


def test_clean_text_produces_no_findings():
    pats = load_patterns(IOCS)
    assert scan_text("module.exports = { plugins: [] };\n", pats, "ok.js") == []


def test_line_numbers_are_one_based_and_correct():
    pats = load_patterns(IOCS)
    found = scan_text("clean\nclean\nhelloipbot\n", pats, "a.js")
    assert found[0].line == 3

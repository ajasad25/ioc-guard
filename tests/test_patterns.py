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


# --- I9: indicators from the incident report's own tables ---

def test_variant_a_campaign_tag_form_is_detected():
    pats = load_patterns(IOCS)
    for body in ("global['!']='9-3266-5';",
                 'global["!"] = "9-1800";',
                 "global [ '!' ] =x"):
        assert scan_text(body, pats, "eslint.config.js"), body


def test_the_campaign_tag_pattern_does_not_fire_on_ordinary_globals():
    pats = load_patterns(IOCS)
    for body in ("global.name = 'x';", "global['crypto'] = require('crypto');",
                 "if (a !== b) { global.x = 1; }"):
        assert scan_text(body, pats, "app.js") == [], body


def test_variant_b_rpc_hosts_are_detected():
    pats = load_patterns(IOCS)
    for host in ("1rpc.io", "blastapi.io", "eth.drpc.org", "eth.blockscout.com"):
        assert scan_text("fetch('https://%s/eth')" % host, pats, "a.js"), host


def test_every_pattern_in_the_file_compiles_and_none_is_empty():
    # load_patterns compiles each line; a bad regex would raise here, and an
    # empty pattern would match every line of every file in every repo.
    pats = load_patterns(IOCS)
    assert len(pats) >= 20
    assert all(label.strip() for label, _ in pats)
    assert all(rx.search("") is None for _, rx in pats), "no pattern may match empty text"


# --- config.bat must not match config.batch ---

def test_config_bat_matches_the_gitignore_artifact():
    pats = load_patterns(IOCS)
    for body in ("config.bat", "config.bat\n", "/config.bat", "**/config.bat",
                 "config.bat.old"):
        assert scan_text(body, pats, ".gitignore"), body


def test_config_bat_does_not_match_config_batch():
    # Measured false positive in two real repos: `config.batch` in Rust source
    # and in a markdown file. Every true positive is the bare filename.
    pats = load_patterns(IOCS)
    for body in ("    let status = if config.batch {",
                 '"--batch" => config.batch = true,',
                 "see config.batching for details",
                 "config.battery"):
        assert scan_text(body, pats, "src/main.rs") == [], body

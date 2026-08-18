"""The README makes claims the operator relies on; keep them present."""
import pathlib

README = (pathlib.Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_readme_documents_the_hookspath_collision():
    # C2: without this, install.sh claims coverage it does not have.
    assert "core.hooksPath" in README
    assert "chain-into-local.sh" in README
    assert "--unset core.hooksPath" in README
    assert "client-side protection" in README
    assert "does not run the global ioc-guard\nhook at all" in README


def test_readme_documents_both_overrides_and_their_difference():
    # I6: the operator must not be trained to reach for the nuclear one.
    assert "IOC_GUARD_SKIP_SCAN=1" in README
    assert "IOC_GUARD=off" in README
    assert "Disables **everything**" in README


def test_readme_states_what_the_control_does_not_catch():
    assert "## What this does not catch" in README
    assert "--no-verify" in README
    assert 'no known indicators' in README

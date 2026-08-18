from ioc_guard.gitdiff import compare_file


def rules(findings):
    return sorted({f.rule for f in findings})


def test_env_rule_removed_from_gitignore_is_flagged():
    base = b"node_modules\n.env\n.env.local\n"
    head = b"node_modules\n"
    assert "diff:gitignore-lost-env" in rules(compare_file(".gitignore", base, head))


def test_gitignore_untouched_is_not_flagged():
    same = b"node_modules\n.env\n"
    assert compare_file(".gitignore", same, same) == []


def test_gitignore_gaining_rules_is_not_flagged():
    base = b".env\n"
    head = b".env\n.env.production\n"
    assert compare_file(".gitignore", base, head) == []


def test_new_gitignore_without_env_is_not_flagged_as_a_loss():
    assert compare_file(".gitignore", b"", b"node_modules\n") == []


def test_wholesale_crlf_conversion_is_flagged():
    base = b"\n".join(b"line %d" % i for i in range(200)) + b"\n"
    head = base.replace(b"\n", b"\r\n")
    assert "diff:crlf-flip" in rules(compare_file("src/app.js", base, head))


def test_file_already_crlf_is_not_flagged():
    base = b"\r\n".join(b"line %d" % i for i in range(200)) + b"\r\n"
    assert compare_file("src/app.js", base, base) == []


def test_small_file_crlf_change_is_not_flagged():
    base = b"a\nb\n"
    assert compare_file("x.js", base, b"a\r\nb\r\n") == []


def test_content_edit_without_line_ending_change_is_not_flagged():
    base = b"\n".join(b"line %d" % i for i in range(200)) + b"\n"
    head = base.replace(b"line 5", b"line five")
    assert compare_file("src/app.js", base, head) == []

from uuid import uuid4

import pytest


def test_password_hash_is_salted_bounded_and_rejects_bad_hashes():
    from app.security.primitives import hash_password, verify_password

    password = "correct horse battery staple 中文"
    first, second = hash_password(password), hash_password(password)
    assert first != second and password not in first
    assert verify_password(password, first)
    assert not verify_password(password + "!", first)
    for bad in [None, "", "scrypt$999999999999$aa$bb", first + "oops"]:
        assert not verify_password(password, bad)
    for bad in ["", "short", "a" * 1025]:
        with pytest.raises(ValueError):
            hash_password(bad)


def test_origin_is_exact_allowlist_and_never_uses_forwarded_headers():
    from app.security.primitives import check_origin

    assert check_origin("http://127.0.0.1:5173", ["http://127.0.0.1:5173"])
    for origin in [
        None,
        "null",
        "http://127.0.0.1:5173.evil",
        "https://evil.test",
        "http://user@127.0.0.1:5173",
        "http://127.0.0.1:5173/path",
    ]:
        assert not check_origin(origin, ["http://127.0.0.1:5173"])


def test_receipt_digest_is_stable_and_includes_target_null_and_version():
    from app.security.primitives import digest

    ident = str(uuid4())
    assert digest({"target": ident, "v": "1", "x": None}) == digest(
        {"x": None, "v": "1", "target": ident}
    )
    assert len({digest(v) for v in [{}, {"x": None}, {"v": "1"}, {"v": "2"}]}) == 4


def test_csrf_check_rejects_non_ascii_and_malformed_without_server_error():
    from app.security.sessions import csrf_for, valid_csrf

    raw = "x" * 43
    assert valid_csrf(raw, csrf_for(raw))
    for bad in [None, "", "a" * 64, "中" * 64, "é" * 64]:
        assert not valid_csrf(raw, bad)


def test_cli_emits_recovery_key_before_a_write_can_be_started(capsys):
    from scripts.accounts import recovery_key

    key = recovery_key(None)
    assert str(key) in capsys.readouterr().err
    supplied = uuid4()
    assert recovery_key(supplied) == supplied
    assert str(supplied) in capsys.readouterr().err

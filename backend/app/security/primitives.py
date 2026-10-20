"""Small fixed-parameter cryptographic primitives. Never accept hash work factors from users."""

import hashlib
import hmac
import json
import secrets
from urllib.parse import urlsplit


def _derive(password, salt):
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**17, r=8, p=1, maxmem=256 * 1024 * 1024, dklen=32
    )


def hash_password(password):
    if not 15 <= len(password) <= 1024:
        raise ValueError("Password must contain 15 to 1024 characters.")
    salt = secrets.token_bytes(16)
    return "scrypt17$" + salt.hex() + "$" + _derive(password, salt).hex()


def verify_password(password, encoded):
    # Unknown, disabled and malformed credentials still perform the same expensive KDF.
    valid, salt, expected = False, bytes(16), bytes(32)
    try:
        kind, salt_hex, expected_hex = encoded.split("$")
        if kind == "scrypt17" and len(salt_hex) == 32 and len(expected_hex) == 64:
            salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(expected_hex)
            valid = True
    except (AttributeError, ValueError):
        pass
    actual = _derive(password if len(password) <= 1024 else "", salt)
    return hmac.compare_digest(actual, expected) and valid and len(password) <= 1024


def token():
    return secrets.token_urlsafe(32)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def check_origin(origin, allowed):
    if not origin or origin not in allowed:
        return False
    try:
        parts = urlsplit(origin)
        return (
            parts.scheme in ("http", "https")
            and parts.hostname is not None
            and not parts.username
            and not parts.password
            and not parts.path
            and not parts.query
            and not parts.fragment
        )
    except ValueError:
        return False

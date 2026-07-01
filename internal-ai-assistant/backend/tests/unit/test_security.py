from __future__ import annotations

import hashlib

from app import security


def test_password_hash_supports_bcrypt_and_legacy_sha256() -> None:
    password = "unit-password-123"
    bcrypt_hash = security.hash_password(password)

    assert bcrypt_hash.startswith("$2")
    assert security.verify_password(password, bcrypt_hash)
    assert not security.verify_password("wrong-password", bcrypt_hash)

    legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    assert security.is_legacy_hash(legacy_hash)
    assert security.verify_password(password, legacy_hash)
    assert not security.verify_password("wrong-password", legacy_hash)


def test_token_refresh_window_uses_exp_claim() -> None:
    fresh_payload = security.decode_token(security.create_token({"sub": "unit-user"}, expires_minutes=120))
    near_expiry_payload = security.decode_token(security.create_token({"sub": "unit-user"}, expires_minutes=5))

    assert security.token_expires_at(fresh_payload) is not None
    assert not security.should_refresh_token(fresh_payload, window_minutes=60)
    assert security.should_refresh_token(near_expiry_payload, window_minutes=60)
    assert security.should_refresh_token({})

from __future__ import annotations

from app.security import security_manager


def test_generate_token_uses_encrypted_claims(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SECURE_JWT_HANDLER_PRIVATE_KEY", "private-key")
    monkeypatch.setenv("SECURE_JWT_HANDLER_PASSWORD", "secret-password")

    captured: dict[str, object] = {}

    def _fake_encrypt(value: str) -> str:
        return f"encrypted::{value}"

    def _fake_generate_token(
        user_id: str,
        tenant_id: str,
        audience: str,
        private_key_base64: str,
        rsa_password: str,
        *,
        data: dict[str, str],
        issued_utc,
        expires_utc,
    ) -> str:
        captured.update(
            {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "audience": audience,
                "private_key_base64": private_key_base64,
                "rsa_password": rsa_password,
                "data": data,
                "issued_utc": issued_utc,
                "expires_utc": expires_utc,
            },
        )
        return "signed-token"

    monkeypatch.setattr(security_manager, "_get_encrypted_data", _fake_encrypt)
    monkeypatch.setattr(security_manager, "generate_token", _fake_generate_token)

    token = security_manager.get_encrypted_token(
        {"token": "raw-token", "session_id": "sk-1234567890"},
    )

    assert token == "signed-token"
    assert captured["user_id"] == "3"
    assert captured["tenant_id"] == "1"
    assert captured["audience"] == "ThirdClient"
    assert captured["private_key_base64"] == "private-key"
    assert captured["rsa_password"] == "secret-password"
    assert captured["data"] == {
        "encrypted_token": "encrypted::raw-token",
        "encrypted_session_id": "encrypted::sk-1234567890",
    }

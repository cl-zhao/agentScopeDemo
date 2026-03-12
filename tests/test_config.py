"""Tests for config loading."""

from __future__ import annotations

from app import config as config_module
from app.config import AppConfig


def test_from_env_loads_model_extra_body_from_toml(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_BASE_URL", "http://localhost:4000/v1")
    monkeypatch.setenv("MODEL_NAME", "demo-model")

    config_file = tmp_path / "model_request.toml"
    config_file.write_text(
        "\n".join(
            [
                "[default]",
                'allowed_openai_params = ["response_format"]',
                'extra_body = { provider_route = "lite" }',
                "",
                '[models."demo-model"]',
                'allowed_openai_params = ["parallel_tool_calls", "tool_choice"]',
                'extra_body = { route = "local" }',
            ],
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "MODEL_REQUEST_CONFIG_PATH", config_file)

    config = AppConfig.from_env()

    assert config.model_extra_body == {
        "provider_route": "lite",
        "route": "local",
        "allowed_openai_params": [
            "response_format",
            "parallel_tool_calls",
            "tool_choice",
        ],
    }

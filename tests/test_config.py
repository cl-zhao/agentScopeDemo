"""Tests for config loading."""

from __future__ import annotations

import pytest

from app import config as config_module
from app.config import AppConfig


def test_from_env_loads_two_layer_model_request_config_from_toml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_BASE_URL", "http://localhost:4000/v1")
    monkeypatch.setenv("MODEL_NAME", "demo-model")

    config_file = tmp_path / "model_request.toml"
    config_file.write_text(
        "\n".join(
            [
                "[global]",
                'non_overridable_openai_params = ["model", "messages"]',
                'non_overridable_provider_params = ["allowed_openai_params", "extra_body"]',
                "",
                "[default]",
                'openai_defaults = { tool_choice = "auto", response_format = "json_object" }',
                'provider_defaults = { top_k = 16 }',
                'extra_body = { provider_route = "lite", nested = { source = "default" } }',
                'litellm_allowed_openai_passthrough = ["response_format"]',
                "",
                '[models."demo-model"]',
                'openai_defaults = { response_format = "json_schema", top_p = 0.8 }',
                'provider_defaults = { repetition_penalty = 1.1 }',
                'extra_body = { route = "local", nested = { source = "model" } }',
                'litellm_allowed_openai_passthrough = ["reasoning_effort"]',
            ],
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "MODEL_REQUEST_CONFIG_PATH", config_file)

    config = AppConfig.from_env()

    assert config.model_request_config.non_overridable_openai_params == [
        "model",
        "messages",
    ]
    assert config.model_request_config.non_overridable_provider_params == [
        "allowed_openai_params",
        "extra_body",
    ]
    assert config.model_request_config.openai_defaults == {
        "tool_choice": "auto",
        "response_format": "json_schema",
        "top_p": 0.8,
    }
    assert config.model_request_config.provider_defaults == {
        "top_k": 16,
        "repetition_penalty": 1.1,
    }
    assert config.model_request_config.extra_body == {
        "provider_route": "lite",
        "route": "local",
        "nested": {"source": "model"},
    }
    assert config.model_request_config.litellm_allowed_openai_passthrough == [
        "response_format",
        "reasoning_effort",
    ]


def test_from_env_rejects_invalid_model_request_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_BASE_URL", "http://localhost:4000/v1")
    monkeypatch.setenv("MODEL_NAME", "demo-model")

    config_file = tmp_path / "model_request.toml"
    config_file.write_text(
        "\n".join(
            [
                "[global]",
                'non_overridable_openai_params = ["model"]',
                'non_overridable_provider_params = ["allowed_openai_params"]',
                "",
                "[default]",
                'openai_defaults = { tool_choice = "auto" }',
                'provider_defaults = { top_k = 16 }',
                'extra_body = { provider_route = "lite" }',
                'litellm_allowed_openai_passthrough = ["response_format"]',
                "",
                '[models."demo-model"]',
                'provider_defaults = "not-a-table"',
            ],
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "MODEL_REQUEST_CONFIG_PATH", config_file)

    with pytest.raises(
        ValueError,
        match="provider_defaults",
    ):
        AppConfig.from_env()


def test_app_config_reads_execution_engine_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_BASE_URL", "http://localhost:4000/v1")
    monkeypatch.setenv("MODEL_NAME", "demo-model")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("REDIS_KEY_PREFIX", "ai-engine")
    monkeypatch.setenv("EXECUTION_RECORD_TTL_SECONDS", "3600")
    monkeypatch.setenv("SESSION_ACTIVE_TTL_SECONDS", "900")
    monkeypatch.setenv("CONTEXT_RECENT_MESSAGE_LIMIT", "8")
    monkeypatch.setenv("CONTEXT_ARTIFACT_CHAR_BUDGET", "12000")
    monkeypatch.setenv("CONTEXT_SUMMARY_BUFFER_FLUSH_MESSAGES", "4")
    monkeypatch.setenv("CONTEXT_SUMMARY_BUFFER_FLUSH_CHARS", "800")
    monkeypatch.setenv("CONTEXT_SUMMARY_MAX_ITEMS_PER_SECTION", "5")
    monkeypatch.setenv("CONTEXT_SUMMARY_MESSAGE_SNIPPET_LENGTH", "60")
    monkeypatch.setenv("CONTEXT_SUMMARY_MAX_LENGTH", "1200")
    monkeypatch.setenv("CONTEXT_STATE_PENDING_QUESTION_LIMIT", "3")

    config = AppConfig.from_env()

    assert config.redis_url == "redis://localhost:6379/0"
    assert config.redis_key_prefix == "ai-engine"
    assert config.execution_record_ttl_seconds == 3600
    assert config.session_active_ttl_seconds == 900
    assert config.context_recent_message_limit == 8
    assert config.context_artifact_char_budget == 12000
    assert config.context_summary_buffer_flush_messages == 4
    assert config.context_summary_buffer_flush_chars == 800
    assert config.context_summary_max_items_per_section == 5
    assert config.context_summary_message_snippet_length == 60
    assert config.context_summary_max_length == 1200
    assert config.context_state_pending_question_limit == 3


def test_app_config_reads_redis_url_from_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_BASE_URL", "http://localhost:4000/v1")
    monkeypatch.setenv("MODEL_NAME", "demo-model")
    monkeypatch.delenv("REDIS_URL", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("REDIS_URL=redis://10.20.30.40:6380/5\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "ENV_FILE_PATH", env_file, raising=False)

    config = AppConfig.from_env()

    assert config.redis_url == "redis://10.20.30.40:6380/5"

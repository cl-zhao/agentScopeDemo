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


def test_app_config_reads_execution_engine_env(monkeypatch) -> None:
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


def test_app_config_reads_redis_url_from_dotenv(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_BASE_URL", "http://localhost:4000/v1")
    monkeypatch.setenv("MODEL_NAME", "demo-model")
    monkeypatch.delenv("REDIS_URL", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("REDIS_URL=redis://10.20.30.40:6380/5\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "ENV_FILE_PATH", env_file, raising=False)

    config = AppConfig.from_env()

    assert config.redis_url == "redis://10.20.30.40:6380/5"

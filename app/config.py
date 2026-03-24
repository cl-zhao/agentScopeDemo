"""应用配置加载。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_REQUEST_CONFIG_PATH = PROJECT_ROOT / "config" / "model_request.toml"
ENV_FILE_PATH = PROJECT_ROOT / ".env"


def _read_required_env(env_name: str) -> str:
    """读取必填环境变量，缺失时抛出明确错误。"""
    value = os.getenv(env_name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {env_name}")
    return value


def _read_optional_float_env(env_name: str, default: float) -> float:
    """读取可选浮点型环境变量，缺失时返回默认值。"""
    value = os.getenv(env_name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {env_name} is not a valid float: {value}",
        ) from exc


def _read_optional_int_env(env_name: str, default: int | None) -> int | None:
    """读取可选整型环境变量，缺失时返回默认值。"""
    value = os.getenv(env_name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {env_name} is not a valid int: {value}",
        ) from exc


def _merge_allowed_openai_params(
        extra_body: dict[str, Any],
        allowed_params: list[str],
) -> dict[str, Any]:
    """将允许透传的 OpenAI 参数合并到请求体中。"""
    if not allowed_params:
        return extra_body

    merged = dict(extra_body)
    existing = merged.get("allowed_openai_params", [])
    if not isinstance(existing, list) or not all(
            isinstance(item, str) for item in existing
    ):
        raise ValueError(
            "allowed_openai_params in extra_body must be a list of strings",
        )

    combined: list[str] = []
    for item in [*existing, *allowed_params]:
        if item not in combined:
            combined.append(item)
    merged["allowed_openai_params"] = combined
    return merged


def _merge_json_objects(
        base: dict[str, Any],
        override: dict[str, Any],
) -> dict[str, Any]:
    """递归合并两个类 JSON 字典。"""
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_json_objects(existing, value)
        else:
            merged[key] = value
    return merged


def _validate_request_section(
        section: Any,
        *,
        section_name: str,
) -> dict[str, Any]:
    """校验单个 TOML 请求配置段并规范化其结构。"""
    if section is None:
        return {"extra_body": {}, "allowed_openai_params": []}
    if not isinstance(section, dict):
        raise ValueError(f"{section_name} must be a TOML table")

    extra_body = section.get("extra_body", {})
    if not isinstance(extra_body, dict):
        raise ValueError(f"{section_name}.extra_body must be a TOML table")

    allowed = section.get("allowed_openai_params", [])
    if not isinstance(allowed, list) or not all(
            isinstance(item, str) for item in allowed
    ):
        raise ValueError(
            f"{section_name}.allowed_openai_params must be a string array",
        )

    return {
        "extra_body": extra_body,
        "allowed_openai_params": allowed,
    }


def _load_model_request_config(
        model_name: str,
        config_path: Path | None = None,
) -> dict[str, Any]:
    """加载指定模型的请求配置覆盖项并完成合并。"""
    if config_path is None:
        config_path = MODEL_REQUEST_CONFIG_PATH
    if not config_path.exists():
        return {}

    with config_path.open("rb") as file:
        parsed = tomllib.load(file)

    if not isinstance(parsed, dict):
        raise ValueError("Model request config root must be a TOML table")

    default_section = _validate_request_section(
        parsed.get("default"),
        section_name="default",
    )
    models_section = parsed.get("models", {})
    if models_section is None:
        models_section = {}
    if not isinstance(models_section, dict):
        raise ValueError("models must be a TOML table")

    model_section = _validate_request_section(
        models_section.get(model_name),
        section_name=f'models."{model_name}"',
    )

    merged_extra_body = _merge_json_objects(
        default_section["extra_body"],
        model_section["extra_body"],
    )
    return _merge_allowed_openai_params(
        merged_extra_body,
        [
            *default_section["allowed_openai_params"],
            *model_section["allowed_openai_params"],
        ],
    )


def _read_mcp_services_transport() -> Literal["streamable_http", "sse"]:
    """从环境变量读取 MCP 服务传输协议。"""
    read_mcp_services_transport = os.getenv(
        "MCP_SERVICES_TRANSPORT",
        default="sse",
    )
    if read_mcp_services_transport not in ["streamable_http", "sse"]:
        raise ValueError(
            "MCP_SERVICES_TRANSPORT must be one of 'streamable_http' or 'sse'",
        )
    return read_mcp_services_transport


class AppConfig(BaseModel):
    ark_api_key: str = Field(description="API key for the OpenAI-compatible endpoint.")
    ark_base_url: str = Field(description="Base URL for the OpenAI-compatible endpoint.")
    ark_model: str = Field(description="Model name.")
    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        description="Redis connection URL for execution control state.",
    )
    redis_key_prefix: str = Field(
        default="ai-engine",
        description="Key prefix used for execution control records in Redis.",
    )
    execution_record_ttl_seconds: int = Field(
        default=3600,
        description="TTL for execution status records stored in Redis.",
    )
    session_active_ttl_seconds: int = Field(
        default=900,
        description="TTL for active session claim records stored in Redis.",
    )
    context_recent_message_limit: int = Field(
        default=8,
        description="Maximum number of recent messages compiled into one execution.",
    )
    context_artifact_char_budget: int = Field(
        default=12000,
        description="Character budget reserved for context artifacts during compilation.",
    )
    context_summary_buffer_flush_messages: int = Field(
        default=4,
        description="Number of buffered evicted messages that should trigger summary compression.",
    )
    context_summary_buffer_flush_chars: int = Field(
        default=800,
        description="Character budget in the summary buffer that should trigger summary compression.",
    )
    context_summary_max_items_per_section: int = Field(
        default=6,
        description="Maximum number of summary bullet items retained per section.",
    )
    context_summary_message_snippet_length: int = Field(
        default=120,
        description="Maximum snippet length used when folding flushed messages into summary bullets.",
    )
    context_summary_max_length: int = Field(
        default=2000,
        description="Maximum total character length of the generated summary text.",
    )
    context_state_pending_question_limit: int = Field(
        default=6,
        description="Maximum number of unresolved state conflict questions retained in task state.",
    )
    model_temperature: float = Field(default=0.2, description="Model temperature.")
    model_max_tokens: int | None = Field(
        default=None,
        description="Maximum tokens for one response.",
    )
    model_extra_body: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional request body forwarded through the gateway.",
    )
    system_prompt: str = Field(
        default=(
            "You are a general task assistant. Understand the user's goal first, "
            "use tools when needed, and return clear actionable results."
        ),
        description="System prompt for the ReAct agent.",
    )
    python_tool_timeout: float = Field(
        default=10.0,
        description="Default timeout for the restricted Python tool.",
    )
    python_tool_max_code_length: int = Field(
        default=4000,
        description="Maximum code length for the restricted Python tool.",
    )
    python_tool_max_output_length: int = Field(
        default=6000,
        description="Maximum output length for the restricted Python tool.",
    )
    mcp_services_transport: Literal["streamable_http", "sse"] = Field(
        default="sse",
        description="MCP services transport protocol.",
    )
    mcp_services_host: str = Field(
        default="http://127.0.0.1:5130/mcp/general/sse",
        description="MCP services host.",
    )
    sqlserver_connection_string: str = Field(
        default="",
        description="SQL Server 连接字符串，格式: DRIVER={ODBC Driver 17 for SQL Server};SERVER=host;DATABASE=db;UID=user;PWD=password",
    )
    sqlserver_max_rows: int = Field(
        default=200,
        description="SQL 查询返回的最大行数。",
    )
    sqlserver_query_timeout: int = Field(
        default=30,
        description="SQL 查询超时时间（秒）。",
    )

    @classmethod
    def from_env(cls) -> "AppConfig":
        """从进程环境变量和项目根目录 `.env` 构建应用配置。"""
        load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)
        ark_model = _read_required_env("MODEL_NAME")
        return cls(
            ark_api_key=_read_required_env("MODEL_API_KEY"),
            ark_base_url=_read_required_env("MODEL_BASE_URL"),
            ark_model=ark_model,
            redis_url=os.getenv(
                "REDIS_URL",
                default="redis://127.0.0.1:6379/0",
            ),
            redis_key_prefix=os.getenv(
                "REDIS_KEY_PREFIX",
                default="ai-engine",
            ),
            execution_record_ttl_seconds=_read_optional_int_env(
                "EXECUTION_RECORD_TTL_SECONDS",
                default=3600,
            )
            or 3600,
            session_active_ttl_seconds=_read_optional_int_env(
                "SESSION_ACTIVE_TTL_SECONDS",
                default=900,
            )
            or 900,
            context_recent_message_limit=_read_optional_int_env(
                "CONTEXT_RECENT_MESSAGE_LIMIT",
                default=8,
            )
            or 8,
            context_artifact_char_budget=_read_optional_int_env(
                "CONTEXT_ARTIFACT_CHAR_BUDGET",
                default=12000,
            )
            or 12000,
            context_summary_buffer_flush_messages=_read_optional_int_env(
                "CONTEXT_SUMMARY_BUFFER_FLUSH_MESSAGES",
                default=4,
            )
            or 4,
            context_summary_buffer_flush_chars=_read_optional_int_env(
                "CONTEXT_SUMMARY_BUFFER_FLUSH_CHARS",
                default=800,
            )
            or 800,
            context_summary_max_items_per_section=_read_optional_int_env(
                "CONTEXT_SUMMARY_MAX_ITEMS_PER_SECTION",
                default=6,
            )
            or 6,
            context_summary_message_snippet_length=_read_optional_int_env(
                "CONTEXT_SUMMARY_MESSAGE_SNIPPET_LENGTH",
                default=120,
            )
            or 120,
            context_summary_max_length=_read_optional_int_env(
                "CONTEXT_SUMMARY_MAX_LENGTH",
                default=2000,
            )
            or 2000,
            context_state_pending_question_limit=_read_optional_int_env(
                "CONTEXT_STATE_PENDING_QUESTION_LIMIT",
                default=6,
            )
            or 6,
            model_temperature=_read_optional_float_env(
                "ARK_TEMPERATURE",
                default=0.2,
            ),
            model_max_tokens=_read_optional_int_env(
                "ARK_MAX_TOKENS",
                default=None,
            ),
            model_extra_body=_load_model_request_config(ark_model),
            python_tool_timeout=_read_optional_float_env(
                "PYTHON_TOOL_TIMEOUT",
                default=10.0,
            ),
            python_tool_max_code_length=_read_optional_int_env(
                "PYTHON_TOOL_MAX_CODE_LENGTH",
                default=4000,
            )
                                        or 4000,
            python_tool_max_output_length=_read_optional_int_env(
                "PYTHON_TOOL_MAX_OUTPUT_LENGTH",
                default=6000,
            )
                                          or 6000,
            system_prompt=os.getenv(
                "AGENT_SYSTEM_PROMPT",
                (
                    "You are a general task assistant. Understand the user's "
                    "goal first, use tools when needed, and return clear "
                    "actionable results."
                ),
            ),
            mcp_services_host=os.getenv(
                "MCP_SERVICES_HOST",
                default="http://127.0.0.1:5130/mcp/general/sse",
            ),
            mcp_services_transport=_read_mcp_services_transport(),
            sqlserver_connection_string=os.getenv(
                "SQLSERVER_CONNECTION_STRING",
                default="",
            ),
            sqlserver_max_rows=_read_optional_int_env(
                "SQLSERVER_MAX_ROWS",
                default=200,
            )
            or 200,
            sqlserver_query_timeout=_read_optional_int_env(
                "SQLSERVER_QUERY_TIMEOUT",
                default=30,
            )
            or 30,

        )

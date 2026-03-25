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


def _dedupe_strings(items: list[str]) -> list[str]:
    """按出现顺序去重字符串列表。"""
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _read_string_array(value: Any, field_name: str) -> list[str]:
    """读取并校验 TOML 中的字符串数组字段。"""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a string array")
    return _dedupe_strings(value)


def _merge_string_lists(*lists: list[str]) -> list[str]:
    """合并多个字符串列表并按出现顺序去重。"""
    merged: list[str] = []
    for items in lists:
        merged.extend(items)
    return _dedupe_strings(merged)


def _merge_json_objects(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个类 JSON 字典。"""
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_json_objects(existing, value)
        else:
            merged[key] = value
    return merged


def _ensure_disjoint_allowed_lists(
    *,
    extra_allowed: list[str],
    blocked_allowed: list[str],
    section_name: str,
) -> None:
    """确保额外允许名单与屏蔽名单没有交集。"""
    overlap = [item for item in extra_allowed if item in blocked_allowed]
    if overlap:
        joined = ", ".join(overlap)
        raise ValueError(
            f"{section_name}.blocked_allowed_openai_params overlaps with "
            f"{section_name}.extra_allowed_openai_params: {joined}",
        )


class ModelRequestLayerConfig(BaseModel):
    """单个配置层中的模型请求参数配置。"""

    model_params: dict[str, Any] = Field(default_factory=dict)
    extra_allowed_openai_params: list[str] = Field(default_factory=list)
    blocked_allowed_openai_params: list[str] = Field(default_factory=list)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ModelRequestConfig(BaseModel):
    """针对单个模型解析完成后的请求兼容配置。"""

    compat_allowed_openai_params: list[str] = Field(default_factory=list)
    non_overridable_request_params: list[str] = Field(default_factory=list)
    model_params: dict[str, Any] = Field(default_factory=dict)
    extra_allowed_openai_params: list[str] = Field(default_factory=list)
    blocked_allowed_openai_params: list[str] = Field(default_factory=list)
    extra_body: dict[str, Any] = Field(default_factory=dict)

    @property
    def allowed_openai_param_hints(self) -> list[str]:
        """返回配置层提供的放行名单提示。"""
        return _merge_string_lists(
            self.compat_allowed_openai_params,
            self.extra_allowed_openai_params,
        )


def _validate_request_global_section(section: Any) -> dict[str, list[str]]:
    """校验 global 配置段并返回规范化结果。"""
    if section is None:
        return {
            "compat_allowed_openai_params": [],
            "non_overridable_request_params": [],
        }
    if not isinstance(section, dict):
        raise ValueError("global must be a TOML table")

    return {
        "compat_allowed_openai_params": _read_string_array(
            section.get("compat_allowed_openai_params", []),
            "global.compat_allowed_openai_params",
        ),
        "non_overridable_request_params": _read_string_array(
            section.get("non_overridable_request_params", []),
            "global.non_overridable_request_params",
        ),
    }


def _validate_request_layer(section: Any, *, section_name: str) -> ModelRequestLayerConfig:
    """校验 default 或 models 下的单层请求配置。"""
    if section is None:
        return ModelRequestLayerConfig()
    if not isinstance(section, dict):
        raise ValueError(f"{section_name} must be a TOML table")

    model_params = section.get("model_params", {})
    if not isinstance(model_params, dict):
        raise ValueError(f"{section_name}.model_params must be a TOML table")

    extra_body = section.get("extra_body", {})
    if not isinstance(extra_body, dict):
        raise ValueError(f"{section_name}.extra_body must be a TOML table")

    extra_allowed = _read_string_array(
        section.get("extra_allowed_openai_params", []),
        f"{section_name}.extra_allowed_openai_params",
    )
    blocked_allowed = _read_string_array(
        section.get("blocked_allowed_openai_params", []),
        f"{section_name}.blocked_allowed_openai_params",
    )
    _ensure_disjoint_allowed_lists(
        extra_allowed=extra_allowed,
        blocked_allowed=blocked_allowed,
        section_name=section_name,
    )

    return ModelRequestLayerConfig(
        model_params=model_params,
        extra_allowed_openai_params=extra_allowed,
        blocked_allowed_openai_params=blocked_allowed,
        extra_body=extra_body,
    )


def _load_model_request_config(
    model_name: str,
    config_path: Path | None = None,
) -> ModelRequestConfig:
    """加载指定模型的请求兼容配置并完成默认层合并。"""
    if config_path is None:
        config_path = MODEL_REQUEST_CONFIG_PATH
    if not config_path.exists():
        return ModelRequestConfig()

    with config_path.open("rb") as file:
        parsed = tomllib.load(file)

    if not isinstance(parsed, dict):
        raise ValueError("Model request config root must be a TOML table")

    global_section = _validate_request_global_section(parsed.get("global"))
    default_section = _validate_request_layer(
        parsed.get("default"),
        section_name="default",
    )

    models_section = parsed.get("models", {})
    if models_section is None:
        models_section = {}
    if not isinstance(models_section, dict):
        raise ValueError("models must be a TOML table")

    model_section = _validate_request_layer(
        models_section.get(model_name),
        section_name=f'models."{model_name}"',
    )

    extra_allowed = _merge_string_lists(
        default_section.extra_allowed_openai_params,
        model_section.extra_allowed_openai_params,
    )
    blocked_allowed = _merge_string_lists(
        default_section.blocked_allowed_openai_params,
        model_section.blocked_allowed_openai_params,
    )
    return ModelRequestConfig(
        compat_allowed_openai_params=global_section["compat_allowed_openai_params"],
        non_overridable_request_params=global_section["non_overridable_request_params"],
        model_params=_merge_json_objects(
            default_section.model_params,
            model_section.model_params,
        ),
        extra_allowed_openai_params=extra_allowed,
        blocked_allowed_openai_params=blocked_allowed,
        extra_body=_merge_json_objects(
            default_section.extra_body,
            model_section.extra_body,
        ),
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
    """应用运行时配置。"""

    ark_api_key: str = Field(description="OpenAI 兼容接口的 API Key。")
    ark_base_url: str = Field(description="OpenAI 兼容接口的基础地址。")
    ark_model: str = Field(description="默认模型名称。")
    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        description="用于执行控制状态的 Redis 连接地址。",
    )
    redis_key_prefix: str = Field(
        default="ai-engine",
        description="Redis 中执行控制记录使用的键前缀。",
    )
    execution_record_ttl_seconds: int = Field(
        default=3600,
        description="Redis 中执行状态记录的过期时间。",
    )
    session_active_ttl_seconds: int = Field(
        default=900,
        description="Redis 中会话活跃占用记录的过期时间。",
    )
    context_recent_message_limit: int = Field(
        default=8,
        description="单次执行编译时纳入的最近消息条数上限。",
    )
    context_artifact_char_budget: int = Field(
        default=12000,
        description="上下文 artifact 编译时保留的字符预算。",
    )
    context_summary_buffer_flush_messages: int = Field(
        default=4,
        description="触发 summary 压缩的缓冲消息条数阈值。",
    )
    context_summary_buffer_flush_chars: int = Field(
        default=800,
        description="触发 summary 压缩的缓冲字符数阈值。",
    )
    context_summary_max_items_per_section: int = Field(
        default=6,
        description="单个 summary 分段保留的最大条目数。",
    )
    context_summary_message_snippet_length: int = Field(
        default=120,
        description="压缩旧消息时单条摘要片段的最大长度。",
    )
    context_summary_max_length: int = Field(
        default=2000,
        description="summary 文本的最大总长度。",
    )
    context_state_pending_question_limit: int = Field(
        default=6,
        description="状态冲突待确认问题的最大保留数。",
    )
    model_temperature: float = Field(default=0.2, description="模型温度。")
    model_max_tokens: int | None = Field(
        default=None,
        description="单次响应的最大 token 数。",
    )
    model_request_config: ModelRequestConfig = Field(
        default_factory=ModelRequestConfig,
        description="解析完成后的模型请求兼容配置。",
    )
    system_prompt: str = Field(
        default=(
            "You are a general task assistant. Understand the user's goal first, "
            "use tools when needed, and return clear actionable results."
        ),
        description="ReAct 智能体的系统提示词。",
    )
    python_tool_timeout: float = Field(
        default=10.0,
        description="受限 Python 工具的默认超时时间。",
    )
    python_tool_max_code_length: int = Field(
        default=4000,
        description="受限 Python 工具允许的最大代码长度。",
    )
    python_tool_max_output_length: int = Field(
        default=6000,
        description="受限 Python 工具允许的最大输出长度。",
    )
    mcp_services_transport: Literal["streamable_http", "sse"] = Field(
        default="sse",
        description="MCP 服务的传输协议。",
    )
    mcp_services_host: str = Field(
        default="http://127.0.0.1:5130/mcp/general/sse",
        description="MCP 服务地址。",
    )
    sqlserver_connection_string: str = Field(
        default="",
        description=(
            "SQL Server 连接字符串，格式: "
            "DRIVER={ODBC Driver 17 for SQL Server};SERVER=host;"
            "DATABASE=db;UID=user;PWD=password"
        ),
    )
    sqlserver_max_rows: int = Field(
        default=200,
        description="SQL 查询返回的最大行数。",
    )
    sqlserver_query_timeout: int = Field(
        default=30,
        description="SQL 查询超时时间（秒）。",
    )

    @property
    def model_extra_body(self) -> dict[str, Any]:
        """兼容旧调用路径，返回解析后的额外请求体。"""
        return dict(self.model_request_config.extra_body)

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
            model_request_config=_load_model_request_config(ark_model),
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

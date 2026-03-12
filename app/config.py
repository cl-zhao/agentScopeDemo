"""Application configuration loading."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_REQUEST_CONFIG_PATH = PROJECT_ROOT / "config" / "model_request.toml"


def _read_required_env(env_name: str) -> str:
    value = os.getenv(env_name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {env_name}")
    return value


def _read_optional_float_env(env_name: str, default: float) -> float:
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
    """Read MCP services transport from environment variable."""
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

    @classmethod
    def from_env(cls) -> "AppConfig":
        ark_model = _read_required_env("MODEL_NAME")
        return cls(
            ark_api_key=_read_required_env("MODEL_API_KEY"),
            ark_base_url=_read_required_env("MODEL_BASE_URL"),
            ark_model=ark_model,
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

        )

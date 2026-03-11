"""应用配置模块。

该模块负责从环境变量加载并校验服务运行所需的配置项。
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


def _read_required_env(env_name: str) -> str:
    """读取必填环境变量。

    参数:
        env_name: 环境变量名称。

    返回:
        读取到的环境变量值。

    异常:
        ValueError: 当环境变量缺失或为空时抛出。
    """
    value = os.getenv(env_name, "").strip()
    if not value:
        raise ValueError(f"缺少必填环境变量: {env_name}")
    return value


def _read_optional_float_env(env_name: str, default: float) -> float:
    """读取可选浮点型环境变量。

    参数:
        env_name: 环境变量名称。
        default: 默认值。

    返回:
        解析后的浮点值。

    异常:
        ValueError: 当环境变量格式非法时抛出。
    """
    value = os.getenv(env_name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {env_name} 不是合法浮点数: {value}") from exc


def _read_optional_int_env(env_name: str, default: int | None) -> int | None:
    """读取可选整型环境变量。

    参数:
        env_name: 环境变量名称。
        default: 默认值，可为 None。

    返回:
        解析后的整型值，或默认值。

    异常:
        ValueError: 当环境变量格式非法时抛出。
    """
    value = os.getenv(env_name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {env_name} 不是合法整数: {value}") from exc


class AppConfig(BaseModel):
    """应用运行配置。

    该配置对象用于统一管理模型接入参数、工具安全参数与默认提示词。
    """

    ark_api_key: str = Field(description="火山引擎 API Key。")
    ark_base_url: str = Field(description="火山引擎 OpenAI 兼容接口 base_url。")
    ark_model: str = Field(description="火山引擎模型名称。")
    model_temperature: float = Field(
        default=0.2,
        description="模型温度参数。",
    )
    model_max_tokens: int | None = Field(
        default=None,
        description="模型单次回复最大 token 数。",
    )
    system_prompt: str = Field(
        default=(
            "你是一个通用任务助理。你需要优先理解用户目标，"
            "必要时调用工具，并给出清晰、可执行的结果。"
        ),
        description="ReAct 智能体系统提示词。",
    )
    python_tool_timeout: float = Field(
        default=10.0,
        description="受限 Python 工具默认超时时间（秒）。",
    )
    python_tool_max_code_length: int = Field(
        default=4000,
        description="受限 Python 工具允许的最大代码长度。",
    )
    python_tool_max_output_length: int = Field(
        default=6000,
        description="受限 Python 工具允许的最大输出长度。",
    )

    @classmethod
    def from_env(cls) -> "AppConfig":
        """从环境变量构建配置对象。

        返回:
            校验完成的 AppConfig 实例。
        """
        return cls(
            ark_api_key=_read_required_env("ARK_API_KEY"),
            ark_base_url=_read_required_env("ARK_BASE_URL"),
            ark_model=_read_required_env("ARK_MODEL"),
            model_temperature=_read_optional_float_env(
                "ARK_TEMPERATURE",
                default=0.2,
            ),
            model_max_tokens=_read_optional_int_env(
                "ARK_MAX_TOKENS",
                default=None,
            ),
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
                    "你是一个通用任务助理。你需要优先理解用户目标，"
                    "必要时调用工具，并给出清晰、可执行的结果。"
                ),
            ),
        )


"""LiteLLM 请求参数组装。"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from agentscope.types import JSONSerializableObject

from app.config import ModelRequestConfig

ENGINE_ALLOWED_OPENAI_PARAMS = ["parallel_tool_calls"]


def _dedupe_strings(items: list[str]) -> list[str]:
    """按出现顺序去重字符串列表。"""
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _merge_string_lists(*lists: list[str]) -> list[str]:
    """合并多个字符串列表并保持顺序稳定。"""
    merged: list[str] = []
    for items in lists:
        merged.extend(items)
    return _dedupe_strings(merged)


@dataclass(slots=True)
class BuiltLitellmRequest:
    """最终发送给 LiteLLM 的参数组装结果。"""

    generate_kwargs: dict[str, JSONSerializableObject]
    agent_parallel_tool_calls: bool
    request_allowed_openai_param_keys: list[str]
    effective_allowed_openai_param_keys: list[str]
    request_overridden_param_keys: list[str]
    final_extra_body_keys: list[str]
    param_sources: dict[str, str]


def build_litellm_request(
    *,
    model_temperature: float,
    model_max_tokens: int | None,
    model_request_config: ModelRequestConfig,
    request_allowed_openai_params: dict[str, Any] | None = None,
) -> BuiltLitellmRequest:
    """构建最终的 LiteLLM `generate_kwargs`。"""
    request_params = dict(request_allowed_openai_params or {})
    generate_kwargs: dict[str, JSONSerializableObject] = {
        "temperature": model_temperature,
        "parallel_tool_calls": True,
    }
    param_sources: dict[str, str] = {
        "temperature": "engine_default",
        "parallel_tool_calls": "engine_default",
    }
    if model_max_tokens is not None:
        generate_kwargs["max_tokens"] = model_max_tokens
        param_sources["max_tokens"] = "engine_default"

    for key, value in model_request_config.model_params.items():
        generate_kwargs[key] = value
        param_sources[key] = "model_config"

    for key, value in request_params.items():
        generate_kwargs[key] = value
        param_sources[key] = "request"

    parallel_tool_calls = generate_kwargs.get("parallel_tool_calls", False)
    if not isinstance(parallel_tool_calls, bool):
        raise ValueError("parallel_tool_calls must be a boolean")

    extra_body = copy.deepcopy(model_request_config.extra_body)
    existing_allowed = extra_body.get("allowed_openai_params", [])
    if existing_allowed:
        if not isinstance(existing_allowed, list) or not all(
            isinstance(item, str) for item in existing_allowed
        ):
            raise ValueError("extra_body.allowed_openai_params must be a string array")

    request_keys = list(request_params.keys())
    blocked_keys = set(model_request_config.blocked_allowed_openai_params) - set(request_keys)
    allowed_keys = _merge_string_lists(
        list(existing_allowed),
        model_request_config.compat_allowed_openai_params,
        model_request_config.extra_allowed_openai_params,
        list(model_request_config.model_params.keys()),
        request_keys,
        [key for key in ENGINE_ALLOWED_OPENAI_PARAMS if key in generate_kwargs],
    )
    effective_allowed_keys = [
        key for key in allowed_keys if key not in blocked_keys
    ]

    if effective_allowed_keys:
        extra_body["allowed_openai_params"] = effective_allowed_keys
    if extra_body:
        generate_kwargs["extra_body"] = extra_body

    return BuiltLitellmRequest(
        generate_kwargs=generate_kwargs,
        agent_parallel_tool_calls=parallel_tool_calls,
        request_allowed_openai_param_keys=request_keys,
        effective_allowed_openai_param_keys=effective_allowed_keys,
        request_overridden_param_keys=request_keys,
        final_extra_body_keys=list(extra_body.keys()),
        param_sources=param_sources,
    )

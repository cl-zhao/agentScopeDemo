"""LiteLLM request assembly helpers."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from agentscope.types import JSONSerializableObject

from app.config import ModelRequestConfig

ENGINE_ALLOWED_OPENAI_PARAMS = ["parallel_tool_calls"]
RESERVED_PROVIDER_PARAMS = {"allowed_openai_params", "extra_body"}


def _dedupe_strings(items: list[str]) -> list[str]:
    """Return strings in first-seen order without duplicates."""
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _merge_string_lists(*lists: list[str]) -> list[str]:
    """Merge lists while preserving first-seen order."""
    merged: list[str] = []
    for items in lists:
        merged.extend(items)
    return _dedupe_strings(merged)


def _merge_json_objects(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge JSON-like dictionaries."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_json_objects(existing, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _merge_extra_body_entry(
    extra_body: dict[str, Any],
    *,
    key: str,
    value: Any,
) -> None:
    existing = extra_body.get(key)
    if isinstance(existing, dict) and isinstance(value, dict):
        extra_body[key] = _merge_json_objects(existing, value)
    else:
        extra_body[key] = copy.deepcopy(value)


def _validate_request_param_partitions(
    *,
    model_request_config: ModelRequestConfig,
    request_openai_params: dict[str, Any],
    request_provider_params: dict[str, Any],
) -> None:
    overlap = [
        key for key in request_openai_params.keys() if key in request_provider_params
    ]
    if overlap:
        joined = ", ".join(overlap)
        raise ValueError(
            f"Found overlap between openai_params and provider_params: {joined}",
        )

    reserved_provider_keys = [
        key
        for key in request_provider_params.keys()
        if key
        in (
            RESERVED_PROVIDER_PARAMS
            | set(model_request_config.non_overridable_provider_params)
        )
    ]
    if reserved_provider_keys:
        joined = ", ".join(reserved_provider_keys)
        raise ValueError(f"provider_params contains reserved keys: {joined}")

    blocked_openai_keys = [
        key
        for key in request_openai_params.keys()
        if key in set(model_request_config.non_overridable_openai_params)
    ]
    if blocked_openai_keys:
        joined = ", ".join(blocked_openai_keys)
        raise ValueError(f"openai_params contains non-overridable keys: {joined}")


@dataclass(slots=True)
class BuiltLitellmRequest:
    """Assembled LiteLLM request payload and diagnostics."""

    generate_kwargs: dict[str, JSONSerializableObject]
    agent_parallel_tool_calls: bool
    request_openai_param_keys: list[str]
    request_provider_param_keys: list[str]
    generated_allowed_openai_param_keys: list[str]
    final_top_level_param_keys: list[str]
    final_extra_body_keys: list[str]
    param_sources: dict[str, str]


def build_litellm_request(
    *,
    model_temperature: float,
    model_max_tokens: int | None,
    model_request_config: ModelRequestConfig,
    request_openai_params: dict[str, Any] | None = None,
    request_provider_params: dict[str, Any] | None = None,
) -> BuiltLitellmRequest:
    """Build final LiteLLM generate kwargs."""
    final_request_openai_params = dict(request_openai_params or {})
    final_request_provider_params = dict(request_provider_params or {})
    _validate_request_param_partitions(
        model_request_config=model_request_config,
        request_openai_params=final_request_openai_params,
        request_provider_params=final_request_provider_params,
    )

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

    for key, value in model_request_config.openai_defaults.items():
        generate_kwargs[key] = copy.deepcopy(value)
        param_sources[key] = "model_openai_default"

    for key, value in final_request_openai_params.items():
        generate_kwargs[key] = copy.deepcopy(value)
        param_sources[key] = "request_openai"

    parallel_tool_calls = generate_kwargs.get("parallel_tool_calls", False)
    if not isinstance(parallel_tool_calls, bool):
        raise ValueError("parallel_tool_calls must be a boolean")

    extra_body = copy.deepcopy(model_request_config.extra_body)
    for key in extra_body.keys():
        param_sources[f"extra_body.{key}"] = "model_extra_body"

    for key, value in model_request_config.provider_defaults.items():
        _merge_extra_body_entry(extra_body, key=key, value=value)
        param_sources[f"extra_body.{key}"] = "model_provider_default"

    for key, value in final_request_provider_params.items():
        _merge_extra_body_entry(extra_body, key=key, value=value)
        param_sources[f"extra_body.{key}"] = "request_provider"

    existing_allowed = extra_body.get("allowed_openai_params", [])
    if existing_allowed:
        if not isinstance(existing_allowed, list) or not all(
            isinstance(item, str) for item in existing_allowed
        ):
            raise ValueError("extra_body.allowed_openai_params must be a string array")

    generated_allowed_openai_param_keys = _merge_string_lists(
        [key for key in ENGINE_ALLOWED_OPENAI_PARAMS if key in generate_kwargs],
        [
            key
            for key in model_request_config.litellm_allowed_openai_passthrough
            if key in generate_kwargs
        ],
        list(existing_allowed),
    )
    if generated_allowed_openai_param_keys:
        extra_body["allowed_openai_params"] = generated_allowed_openai_param_keys
        param_sources["extra_body.allowed_openai_params"] = (
            "generated_allowed_openai_passthrough"
        )

    if extra_body:
        generate_kwargs["extra_body"] = extra_body

    return BuiltLitellmRequest(
        generate_kwargs=generate_kwargs,
        agent_parallel_tool_calls=parallel_tool_calls,
        request_openai_param_keys=list(final_request_openai_params.keys()),
        request_provider_param_keys=list(final_request_provider_params.keys()),
        generated_allowed_openai_param_keys=generated_allowed_openai_param_keys,
        final_top_level_param_keys=list(generate_kwargs.keys()),
        final_extra_body_keys=list(extra_body.keys()),
        param_sources=param_sources,
    )

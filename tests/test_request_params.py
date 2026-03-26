"""Tests for LiteLLM request param building."""

from __future__ import annotations

import pytest

from app.agent.request_params import build_litellm_request
from app.config import ModelRequestConfig


def test_build_litellm_request_splits_openai_and_provider_params() -> None:
    built = build_litellm_request(
        model_temperature=0.1,
        model_max_tokens=256,
        model_request_config=ModelRequestConfig(
            openai_defaults={
                "tool_choice": "auto",
                "response_format": {"type": "json_schema", "name": "default"},
            },
            provider_defaults={
                "top_k": 16,
                "routing": {"region": "cn", "tier": "default"},
            },
            extra_body={"provider_route": "lite"},
            litellm_allowed_openai_passthrough=[
                "response_format",
                "reasoning_effort",
            ],
        ),
        request_openai_params={
            "parallel_tool_calls": False,
            "reasoning_effort": "high",
            "response_format": {"type": "json_schema", "name": "override"},
        },
        request_provider_params={
            "top_k": 32,
            "repetition_penalty": 1.1,
            "routing": {"tier": "premium"},
        },
    )

    assert built.generate_kwargs == {
        "temperature": 0.1,
        "parallel_tool_calls": False,
        "max_tokens": 256,
        "tool_choice": "auto",
        "response_format": {"type": "json_schema", "name": "override"},
        "reasoning_effort": "high",
        "extra_body": {
            "provider_route": "lite",
            "top_k": 32,
            "routing": {"region": "cn", "tier": "premium"},
            "repetition_penalty": 1.1,
            "allowed_openai_params": [
                "parallel_tool_calls",
                "response_format",
                "reasoning_effort",
            ],
        },
    }
    assert built.agent_parallel_tool_calls is False
    assert built.request_openai_param_keys == [
        "parallel_tool_calls",
        "reasoning_effort",
        "response_format",
    ]
    assert built.request_provider_param_keys == [
        "top_k",
        "repetition_penalty",
        "routing",
    ]
    assert built.generated_allowed_openai_param_keys == [
        "parallel_tool_calls",
        "response_format",
        "reasoning_effort",
    ]
    assert built.final_top_level_param_keys == [
        "temperature",
        "parallel_tool_calls",
        "max_tokens",
        "tool_choice",
        "response_format",
        "reasoning_effort",
        "extra_body",
    ]
    assert built.final_extra_body_keys == [
        "provider_route",
        "top_k",
        "routing",
        "repetition_penalty",
        "allowed_openai_params",
    ]
    assert built.param_sources == {
        "temperature": "engine_default",
        "parallel_tool_calls": "request_openai",
        "max_tokens": "engine_default",
        "tool_choice": "model_openai_default",
        "response_format": "request_openai",
        "reasoning_effort": "request_openai",
        "extra_body.provider_route": "model_extra_body",
        "extra_body.top_k": "request_provider",
        "extra_body.routing": "request_provider",
        "extra_body.repetition_penalty": "request_provider",
        "extra_body.allowed_openai_params": "generated_allowed_openai_passthrough",
    }


@pytest.mark.parametrize(
    ("request_openai_params", "request_provider_params", "message"),
    [
        (
            {"top_k": 0.8},
            {"top_k": 16},
            "overlap between openai_params and provider_params",
        ),
        (
            {},
            {"allowed_openai_params": ["top_k"]},
            "provider_params contains reserved keys",
        ),
    ],
)
def test_build_litellm_request_rejects_invalid_param_partitions(
    request_openai_params: dict[str, object],
    request_provider_params: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_litellm_request(
            model_temperature=0.1,
            model_max_tokens=None,
            model_request_config=ModelRequestConfig(),
            request_openai_params=request_openai_params,
            request_provider_params=request_provider_params,
        )

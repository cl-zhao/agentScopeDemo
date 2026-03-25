"""factory 模块单元测试。"""

from __future__ import annotations

import asyncio
from zoneinfo import ZoneInfoNotFoundError

import pytest

from app.agent.factory import AgentFactory
from app.config import AppConfig, ModelRequestConfig
from app.tools import PythonSafetyConfig, SafePythonExecutor


def test_create_agent_attaches_gateway_extra_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 create_agent 会合并模型默认参数与请求级透传参数。"""
    config = AppConfig(
        ark_api_key="sk-test",
        ark_base_url="http://localhost:4000/v1",
        ark_model="demo-model",
        model_temperature=0.1,
        model_max_tokens=256,
        model_request_config=ModelRequestConfig(
            compat_allowed_openai_params=[
                "parallel_tool_calls",
                "response_format",
            ],
            model_params={
                "tool_choice": "auto",
                "response_format": "json_schema",
            },
            extra_allowed_openai_params=["reasoning_effort"],
            blocked_allowed_openai_params=["response_format"],
            extra_body={"provider_route": "lite"},
        ),
        python_tool_timeout=1.0,
        python_tool_max_code_length=1000,
        python_tool_max_output_length=1000,
    )
    executor = SafePythonExecutor(PythonSafetyConfig())

    async def _fake_reg_mcp(*args: object, **kwargs: object) -> object:
        return args[0]

    monkeypatch.setattr("app.agent.factory.reg_mcp_function_level_usage", _fake_reg_mcp)
    monkeypatch.setattr(
        "app.agent.factory.register_mcp_tracking_middleware",
        lambda **kwargs: None,
    )

    async def _run() -> None:
        agent_factory = AgentFactory(config=config, python_executor=executor)
        agent = await agent_factory.create_agent(
            request_allowed_openai_params={
                "parallel_tool_calls": False,
                "reasoning_effort": "high",
                "response_format": "json_schema_override",
            }
        )

        assert agent.model.generate_kwargs["parallel_tool_calls"] is False
        assert agent.model.generate_kwargs["max_tokens"] == 256
        assert agent.model.generate_kwargs["tool_choice"] == "auto"
        assert agent.model.generate_kwargs["response_format"] == "json_schema_override"
        assert agent.model.generate_kwargs["reasoning_effort"] == "high"
        assert agent.model.generate_kwargs["extra_body"] == {
            "provider_route": "lite",
            "allowed_openai_params": [
                "parallel_tool_calls",
                "response_format",
                "reasoning_effort",
                "tool_choice",
            ],
        }
        assert "read_agent_skill_file" in agent.toolkit.tools
        assert "order_complete_quantity_query" in agent.toolkit.skills
        assert "智能派工" in agent.toolkit.skills
        assert "sample_skill" not in agent.toolkit.skills
        assert "must call `read_agent_skill_file` first" in agent.sys_prompt
        assert agent._litellm_request_diagnostics == {
            "request_allowed_openai_param_keys": [
                "parallel_tool_calls",
                "reasoning_effort",
                "response_format",
            ],
            "effective_allowed_openai_param_keys": [
                "parallel_tool_calls",
                "response_format",
                "reasoning_effort",
                "tool_choice",
            ],
            "request_overridden_param_keys": [
                "parallel_tool_calls",
                "reasoning_effort",
                "response_format",
            ],
            "final_extra_body_keys": ["provider_route", "allowed_openai_params"],
            "param_sources": {
                "temperature": "engine_default",
                "parallel_tool_calls": "request",
                "max_tokens": "engine_default",
                "tool_choice": "model_config",
                "response_format": "request",
                "reasoning_effort": "request",
            },
        }

    asyncio.run(_run())


def test_get_current_time_falls_back_to_builtin_utc_when_zoneinfo_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        ark_api_key="sk-test",
        ark_base_url="http://localhost:4000/v1",
        ark_model="demo-model",
        python_tool_timeout=1.0,
        python_tool_max_code_length=1000,
        python_tool_max_output_length=1000,
    )
    executor = SafePythonExecutor(PythonSafetyConfig())
    agent_factory = AgentFactory(config=config, python_executor=executor)

    def _raise_zoneinfo_not_found(_: str) -> object:
        raise ZoneInfoNotFoundError("No time zone found")

    monkeypatch.setattr("app.agent.factory.ZoneInfo", _raise_zoneinfo_not_found)

    async def _run() -> str:
        response = await agent_factory.get_current_time()
        first_block = response.content[0]
        return first_block["text"] if isinstance(first_block, dict) else first_block.text

    assert "UTC" in asyncio.run(_run())

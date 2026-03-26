"""Unit tests for the agent factory."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.factory import AgentFactory
from app.config import AppConfig, ModelRequestConfig
from app.tools import PythonSafetyConfig, SafePythonExecutor


def test_create_agent_attaches_gateway_extra_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        ark_api_key="sk-test",
        ark_base_url="http://localhost:4000/v1",
        ark_model="demo-model",
        model_temperature=0.1,
        model_max_tokens=256,
        model_request_config=ModelRequestConfig(
            openai_defaults={
                "tool_choice": "auto",
                "response_format": "json_schema",
            },
            provider_defaults={"top_k": 16},
            extra_body={"provider_route": "lite", "routing": {"region": "cn"}},
            litellm_allowed_openai_passthrough=[
                "response_format",
                "reasoning_effort",
            ],
        ),
        python_tool_timeout=1.0,
        python_tool_max_code_length=1000,
        python_tool_max_output_length=1000,
    )
    executor = SafePythonExecutor(PythonSafetyConfig())

    async def _fake_reg_mcp(*args: object, **kwargs: object) -> object:
        _ = kwargs
        return args[0]

    monkeypatch.setattr("app.agent.factory.reg_mcp_function_level_usage", _fake_reg_mcp)
    monkeypatch.setattr(
        "app.agent.factory.register_mcp_tracking_middleware",
        lambda **kwargs: None,
    )

    async def _run() -> None:
        agent_factory = AgentFactory(config=config, python_executor=executor)
        agent = await agent_factory.create_agent(
            request_openai_params={
                "parallel_tool_calls": False,
                "reasoning_effort": "high",
                "response_format": "json_schema_override",
            },
            request_provider_params={
                "top_k": 32,
                "repetition_penalty": 1.1,
                "routing": {"tier": "premium"},
            },
        )

        assert agent.model.generate_kwargs["parallel_tool_calls"] is False
        assert agent.model.generate_kwargs["max_tokens"] == 256
        assert agent.model.generate_kwargs["tool_choice"] == "auto"
        assert agent.model.generate_kwargs["response_format"] == "json_schema_override"
        assert agent.model.generate_kwargs["reasoning_effort"] == "high"
        assert agent.model.generate_kwargs["extra_body"] == {
            "provider_route": "lite",
            "routing": {"region": "cn", "tier": "premium"},
            "top_k": 32,
            "repetition_penalty": 1.1,
            "allowed_openai_params": [
                "parallel_tool_calls",
                "response_format",
                "reasoning_effort",
            ],
        }
        assert "read_agent_skill_file" in agent.toolkit.tools
        assert "order_complete_quantity_query" in agent.toolkit.skills
        assert "智能派工" in agent.toolkit.skills
        assert "sample_skill" not in agent.toolkit.skills
        assert "must call `read_agent_skill_file` first" in agent.sys_prompt
        assert agent._litellm_request_diagnostics == {
            "request_openai_param_keys": [
                "parallel_tool_calls",
                "reasoning_effort",
                "response_format",
            ],
            "request_provider_param_keys": [
                "top_k",
                "repetition_penalty",
                "routing",
            ],
            "generated_allowed_openai_param_keys": [
                "parallel_tool_calls",
                "response_format",
                "reasoning_effort",
            ],
            "final_top_level_param_keys": [
                "temperature",
                "parallel_tool_calls",
                "max_tokens",
                "tool_choice",
                "response_format",
                "reasoning_effort",
                "extra_body",
            ],
            "final_extra_body_keys": [
                "provider_route",
                "routing",
                "top_k",
                "repetition_penalty",
                "allowed_openai_params",
            ],
            "param_sources": {
                "temperature": "engine_default",
                "parallel_tool_calls": "request_openai",
                "max_tokens": "engine_default",
                "tool_choice": "model_openai_default",
                "response_format": "request_openai",
                "reasoning_effort": "request_openai",
                "extra_body.provider_route": "model_extra_body",
                "extra_body.routing": "request_provider",
                "extra_body.top_k": "request_provider",
                "extra_body.repetition_penalty": "request_provider",
                "extra_body.allowed_openai_params": (
                    "generated_allowed_openai_passthrough"
                ),
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


def test_create_agent_survives_mcp_registration_degradation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = AppConfig(
        ark_api_key="sk-test",
        ark_base_url="http://localhost:4000/v1",
        ark_model="demo-model",
        mcp_services_transport="sse",
        mcp_services_host="http://mcp.example.test",
        python_tool_timeout=1.0,
        python_tool_max_code_length=1000,
        python_tool_max_output_length=1000,
    )
    executor = SafePythonExecutor(PythonSafetyConfig())

    class FakeHttpStatelessClient:
        def __init__(self, *, name: str, transport: str, url: str) -> None:
            self.name = name
            self.transport = transport
            self.url = url

    async def _raise_connection_error(
        self: object,
        client: object,
        group_name: str | None = None,
    ) -> None:
        _ = self, client, group_name
        raise ConnectionError("offline")

    monkeypatch.setattr("app.agent.mcp_registry.HttpStatelessClient", FakeHttpStatelessClient)
    monkeypatch.setattr("agentscope.tool.Toolkit.register_mcp_client", _raise_connection_error)
    monkeypatch.setattr(
        "app.agent.factory.register_mcp_tracking_middleware",
        lambda **kwargs: None,
    )
    caplog.set_level(logging.WARNING, logger="app.agent.mcp_registry")

    async def _run() -> object:
        agent_factory = AgentFactory(config=config, python_executor=executor)
        return await agent_factory.create_agent()

    agent = asyncio.run(_run())

    assert "get_current_time" in agent.toolkit.tools
    assert "evaluate_expression" in agent.toolkit.tools
    assert "read_agent_skill_file" in agent.toolkit.tools
    assert any(
        record.levelno == logging.WARNING
        and record.name == "app.agent.mcp_registry"
        and "skipp" in record.message.lower()
        and "transport=sse" in record.message
        and "host=http://mcp.example.test" in record.message
        for record in caplog.records
    )
    assert "skipp" in caplog.text.lower()
    assert "transport=sse" in caplog.text
    assert "host=http://mcp.example.test" in caplog.text
    assert "offline" in caplog.text

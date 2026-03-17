"""factory 模块单元测试。"""

from __future__ import annotations

import pytest

from app.agent.factory import AgentFactory
from app.config import AppConfig
from app.tools import PythonSafetyConfig, SafePythonExecutor


@pytest.mark.asyncio
async def test_create_agent_attaches_gateway_extra_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 create_agent 会将 extra_body 透传给模型生成参数。"""
    config = AppConfig(
        ark_api_key="sk-test",
        ark_base_url="http://localhost:4000/v1",
        ark_model="demo-model",
        model_temperature=0.1,
        model_max_tokens=256,
        model_extra_body={
            "allowed_openai_params": ["parallel_tool_calls", "response_format"],
        },
        python_tool_timeout=1.0,
        python_tool_max_code_length=1000,
        python_tool_max_output_length=1000,
    )
    executor = SafePythonExecutor(PythonSafetyConfig())

    async def _fake_reg_mcp(*args: object, **kwargs: object) -> object:
        return args[0]

    monkeypatch.setattr("app.agent.factory.reg_mcp_function_level_usage", _fake_reg_mcp)

    agent_factory = AgentFactory(config=config, python_executor=executor)
    agent = await agent_factory.create_agent()

    assert agent.model.generate_kwargs["parallel_tool_calls"] is True
    assert agent.model.generate_kwargs["max_tokens"] == 256
    assert agent.model.generate_kwargs["extra_body"] == {
        "allowed_openai_params": ["parallel_tool_calls", "response_format"],
    }
    assert "read_agent_skill_file" in agent.toolkit.tools
    assert "order_complete_quantity_query" in agent.toolkit.skills
    assert "sample_skill" not in agent.toolkit.skills
    assert "must call `read_agent_skill_file` first" in agent.sys_prompt

"""MCP trace middleware tests."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator

import pytest
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse, Toolkit

from app.agent.mcp_trace import MCP_TRACE_BLOCK_TYPE, register_mcp_tracking_middleware


class FakeStreamingAgent:
    """Minimal agent stub exposing msg_queue for trace middleware."""

    def __init__(self) -> None:
        self.msg_queue: asyncio.Queue = asyncio.Queue()


async def _dummy_tool(query: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=query)])


def _build_next_handler(
    *responses: ToolResponse,
    error: Exception | None = None,
) -> Any:
    async def _next_handler(**kwargs: Any) -> AsyncGenerator[ToolResponse, None]:
        _ = kwargs

        async def _stream() -> AsyncGenerator[ToolResponse, None]:
            for response in responses:
                yield response
            if error is not None:
                raise error

        return _stream()

    return _next_handler


async def _drain_trace_statuses(
    agent: FakeStreamingAgent,
) -> list[tuple[dict[str, Any], bool]]:
    queued: list[tuple[dict[str, Any], bool]] = []
    while not agent.msg_queue.empty():
        message, is_last, _speech = await agent.msg_queue.get()
        block = message.get_content_blocks(MCP_TRACE_BLOCK_TYPE)[0]
        queued.append((block, is_last))
    return queued


def _build_tool_call(name: str = "_dummy_tool") -> dict[str, Any]:
    return {
        "id": "tool-call-1",
        "name": name,
        "input": {"query": "hello"},
    }


@pytest.mark.asyncio
async def test_mcp_trace_middleware_emits_started_running_and_completed() -> None:
    toolkit = Toolkit()
    toolkit.register_tool_function(_dummy_tool)
    toolkit.tools["_dummy_tool"].mcp_name = "docs-server"
    toolkit.tools["_dummy_tool"].original_name = "remote_search"
    agent = FakeStreamingAgent()
    register_mcp_tracking_middleware(toolkit=toolkit, agent=agent)

    responses = [
        ToolResponse(
            content=[TextBlock(type="text", text="partial")],
            stream=True,
            is_last=False,
        ),
        ToolResponse(
            content=[TextBlock(type="text", text="done")],
            stream=True,
            is_last=True,
        ),
    ]
    stream = toolkit._middlewares[0](  # noqa: SLF001 - validate registered middleware behavior
        {"tool_call": _build_tool_call()},
        _build_next_handler(*responses),
    )

    collected = [response async for response in stream]
    queued = await _drain_trace_statuses(agent)

    assert collected == responses
    assert [item[0]["status"] for item in queued] == ["started", "running", "completed"]
    assert [item[1] for item in queued] == [False, False, True]
    assert queued[-1][0]["mcp_name"] == "docs-server"
    assert queued[-1][0]["mcp_method"] == "remote_search"
    assert queued[-1][0]["result"] == [{"type": "text", "text": "done"}]


@pytest.mark.asyncio
async def test_mcp_trace_middleware_marks_failed_from_mcp_error_text() -> None:
    toolkit = Toolkit()
    toolkit.register_tool_function(_dummy_tool)
    toolkit.tools["_dummy_tool"].mcp_name = "docs-server"
    agent = FakeStreamingAgent()
    register_mcp_tracking_middleware(toolkit=toolkit, agent=agent)

    response = ToolResponse(
        content=[
            TextBlock(
                type="text",
                text="Error occurred when calling MCP tool: boom",
            ),
        ],
    )
    stream = toolkit._middlewares[0](  # noqa: SLF001 - validate registered middleware behavior
        {"tool_call": _build_tool_call()},
        _build_next_handler(response),
    )

    _ = [chunk async for chunk in stream]
    queued = await _drain_trace_statuses(agent)

    assert [item[0]["status"] for item in queued] == ["started", "running", "failed"]
    assert queued[-1][0]["error"] == "Error occurred when calling MCP tool: boom"


@pytest.mark.asyncio
async def test_mcp_trace_middleware_marks_interrupted() -> None:
    toolkit = Toolkit()
    toolkit.register_tool_function(_dummy_tool)
    toolkit.tools["_dummy_tool"].mcp_name = "docs-server"
    agent = FakeStreamingAgent()
    register_mcp_tracking_middleware(toolkit=toolkit, agent=agent)

    response = ToolResponse(
        content=[TextBlock(type="text", text="partial")],
        is_interrupted=True,
    )
    stream = toolkit._middlewares[0](  # noqa: SLF001 - validate registered middleware behavior
        {"tool_call": _build_tool_call()},
        _build_next_handler(response),
    )

    _ = [chunk async for chunk in stream]
    queued = await _drain_trace_statuses(agent)

    assert [item[0]["status"] for item in queued] == ["started", "running", "interrupted"]
    assert queued[-1][1] is True


@pytest.mark.asyncio
async def test_mcp_trace_middleware_skips_non_mcp_tools() -> None:
    toolkit = Toolkit()
    toolkit.register_tool_function(_dummy_tool)
    agent = FakeStreamingAgent()
    register_mcp_tracking_middleware(toolkit=toolkit, agent=agent)

    response = ToolResponse(content=[TextBlock(type="text", text="plain")])
    stream = toolkit._middlewares[0](  # noqa: SLF001 - validate registered middleware behavior
        {"tool_call": _build_tool_call()},
        _build_next_handler(response),
    )

    collected = [chunk async for chunk in stream]

    assert collected == [response]
    assert agent.msg_queue.empty()

"""Helpers for streaming MCP call trace events through AgentScope msg_queue."""

from __future__ import annotations

import asyncio
import copy
from typing import Any, AsyncGenerator

from agentscope.message import Msg
from agentscope.message._message_block import ToolUseBlock
from agentscope.tool import ToolResponse, Toolkit

MCP_TRACE_BLOCK_TYPE = "mcp_trace"
MCP_TRACE_TERMINAL_STATUSES = {"completed", "failed", "interrupted"}
_MCP_ERROR_PREFIXES = (
    "Error occurred when calling MCP tool:",
    "Error:",
)


def normalize_stream_output(output: Any) -> Any:
    """Normalize tool output into JSON-serializable data."""
    if isinstance(output, list):
        normalized = []
        for item in output:
            if isinstance(item, dict):
                normalized.append(copy.deepcopy(item))
            else:
                normalized.append(str(item))
        return normalized
    if isinstance(output, dict):
        return copy.deepcopy(output)
    if isinstance(output, (str, int, float, bool, type(None))):
        return output
    return str(output)


def build_mcp_trace_msg(
    *,
    tool_id: str,
    tool_name: str,
    mcp_name: str,
    mcp_method: str,
    status: str,
    result: Any = None,
    error: str | None = None,
) -> Msg:
    """Build a synthetic Msg used only for SSE streaming."""
    return Msg(
        name="system",
        role="system",
        content=[
            {
                "type": MCP_TRACE_BLOCK_TYPE,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "mcp_name": mcp_name,
                "mcp_method": mcp_method,
                "status": status,
                "result": normalize_stream_output(result),
                "error": error,
            },
        ],
    )


def detect_mcp_failure(output: Any) -> str | None:
    """Infer whether the final MCP output represents a failure."""
    text = _extract_text_output(output)
    if not text:
        return None

    for prefix in _MCP_ERROR_PREFIXES:
        if text.startswith(prefix):
            return text
    return None


def register_mcp_tracking_middleware(toolkit: Toolkit, agent: Any) -> None:
    """Register middleware that emits MCP trace messages into agent.msg_queue."""

    async def mcp_tracking_middleware(
        kwargs: dict[str, Any],
        next_handler: Any,
    ) -> AsyncGenerator[ToolResponse, None]:
        tool_call = kwargs["tool_call"]
        registered_tool = toolkit.tools.get(tool_call["name"])

        if registered_tool is None or not registered_tool.mcp_name:
            async for response in await next_handler(**kwargs):
                yield response
            return

        mcp_name = registered_tool.mcp_name
        mcp_method = registered_tool.original_name or registered_tool.name
        await _emit_mcp_trace(
            agent=agent,
            tool_call=tool_call,
            mcp_name=mcp_name,
            mcp_method=mcp_method,
            status="started",
        )
        await _emit_mcp_trace(
            agent=agent,
            tool_call=tool_call,
            mcp_name=mcp_name,
            mcp_method=mcp_method,
            status="running",
        )

        last_output: Any = None
        interrupted = False
        try:
            async for response in await next_handler(**kwargs):
                last_output = copy.deepcopy(response.content)
                interrupted = interrupted or bool(response.is_interrupted)
                yield response
        except Exception as exc:  # noqa: BLE001 - preserve original failure path
            await _emit_mcp_trace(
                agent=agent,
                tool_call=tool_call,
                mcp_name=mcp_name,
                mcp_method=mcp_method,
                status="failed",
                error=str(exc),
            )
            raise

        normalized_result = normalize_stream_output(last_output)
        if interrupted:
            await _emit_mcp_trace(
                agent=agent,
                tool_call=tool_call,
                mcp_name=mcp_name,
                mcp_method=mcp_method,
                status="interrupted",
                result=normalized_result,
            )
            return

        error = detect_mcp_failure(last_output)
        if error is not None:
            await _emit_mcp_trace(
                agent=agent,
                tool_call=tool_call,
                mcp_name=mcp_name,
                mcp_method=mcp_method,
                status="failed",
                result=normalized_result,
                error=error,
            )
            return

        await _emit_mcp_trace(
            agent=agent,
            tool_call=tool_call,
            mcp_name=mcp_name,
            mcp_method=mcp_method,
            status="completed",
            result=normalized_result,
        )

    toolkit.register_middleware(mcp_tracking_middleware)


async def _emit_mcp_trace(
    *,
    agent: Any,
    tool_call: ToolUseBlock,
    mcp_name: str,
    mcp_method: str,
    status: str,
    result: Any = None,
    error: str | None = None,
) -> None:
    queue = getattr(agent, "msg_queue", None)
    if queue is None:
        return

    message = build_mcp_trace_msg(
        tool_id=tool_call["id"],
        tool_name=tool_call["name"],
        mcp_name=mcp_name,
        mcp_method=mcp_method,
        status=status,
        result=result,
        error=error,
    )
    await queue.put((message, status in MCP_TRACE_TERMINAL_STATUSES, None))
    await asyncio.sleep(0)


def _extract_text_output(output: Any) -> str:
    if isinstance(output, str):
        return output.strip()
    if not isinstance(output, list):
        return ""

    texts: list[str] = []
    for item in output:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(texts).strip()

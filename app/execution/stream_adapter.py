"""将 AgentScope 消息适配为流式事件的辅助模块。"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from agentscope.message import Msg
from agentscope.message._message_block import ToolResultBlock, ToolUseBlock

from app.agent.mcp_trace import MCP_TRACE_BLOCK_TYPE, normalize_stream_output


class StreamEventAdapter:
    """将累计式 AgentScope 消息转换为增量式 SSE 事件。"""

    def __init__(self) -> None:
        """初始化用于计算增量流差异的消息级缓存。"""
        self._assistant_text_cache: dict[str, str] = {}
        self._assistant_thinking_cache: dict[str, str] = {}
        self._closed_thinking_messages: set[str] = set()
        self._tool_call_cache: dict[str, str] = {}
        self._tool_result_cache: dict[str, str] = {}
        self._mcp_trace_cache: set[str] = set()
        self._tool_input_cache: dict[str, dict[str, Any] | None] = {}
        self._tool_name_cache: dict[str, str] = {}
        self._mcp_tool_ids: set[str] = set()

    def extract_events(self, msg: Msg, is_last: bool) -> list[tuple[str, dict[str, Any]]]:
        """将一条累计式 AgentScope 消息转换为零个或多个 SSE 事件。"""
        events: list[tuple[str, dict[str, Any]]] = []

        if msg.role == "assistant":
            delta, current_text = self._extract_assistant_delta(msg)
            thinking_delta, current_thinking = self._extract_assistant_thinking_delta(msg)
            if thinking_delta:
                events.append(
                    (
                        "thinking_chunk",
                        {
                            "message_id": msg.id,
                            "thinking": thinking_delta,
                            "is_last": False,
                        },
                    )
                )
            if self._should_close_thinking_before_text(
                message_id=msg.id,
                current_text=current_text,
                current_thinking=current_thinking,
            ):
                events.append(
                    (
                        "thinking_chunk",
                        {
                            "message_id": msg.id,
                            "thinking": "",
                            "is_last": True,
                        },
                    )
                )
                self._closed_thinking_messages.add(msg.id)
            elif self._should_close_thinking_on_message_end(
                message_id=msg.id,
                current_thinking=current_thinking,
                is_last=is_last,
            ):
                events.append(
                    (
                        "thinking_chunk",
                        {
                            "message_id": msg.id,
                            "thinking": "",
                            "is_last": True,
                        },
                    )
                )
                self._closed_thinking_messages.add(msg.id)
            if delta or (is_last and current_text):
                events.append(
                    (
                        "assistant_chunk",
                        {
                            "message_id": msg.id,
                            "text": delta,
                            "is_last": is_last,
                        },
                    )
                )

        for block in msg.get_content_blocks("tool_use"):
            tool_event = self._build_tool_call_event(block, is_last=is_last)
            if tool_event is not None:
                events.append(("tool_call", tool_event))

        for block in msg.get_content_blocks("tool_result"):
            result_event = self._build_tool_result_event(block)
            if result_event is not None:
                events.append(("tool_call", result_event))

        for block in msg.get_content_blocks(MCP_TRACE_BLOCK_TYPE):
            trace_event = self._build_mcp_trace_event(block)
            if trace_event is not None:
                events.append(("tool_call", trace_event))

        return events

    def _extract_assistant_delta(self, msg: Msg) -> tuple[str, str]:
        """计算指定消息 ID 新增的 assistant 文本片段。"""
        current_text = msg.get_text_content(separator="\n") or ""
        previous_text = self._assistant_text_cache.get(msg.id, "")
        if current_text.startswith(previous_text):
            delta = current_text[len(previous_text) :]
        else:
            # 如果上游重写了整段 assistant 内容，则直接发出全文，避免重建流时静默丢字。
            delta = current_text
        self._assistant_text_cache[msg.id] = current_text
        return delta, current_text

    def _extract_assistant_thinking_delta(self, msg: Msg) -> tuple[str, str]:
        """计算指定消息 ID 新增的 assistant thinking 文本片段。"""
        thinking_blocks = msg.get_content_blocks("thinking")
        current_thinking = "\n".join(
            block.get("thinking", "")
            for block in thinking_blocks
            if isinstance(block.get("thinking", ""), str)
        )
        previous_thinking = self._assistant_thinking_cache.get(msg.id, "")
        if current_thinking.startswith(previous_thinking):
            delta = current_thinking[len(previous_thinking) :]
        else:
            delta = current_thinking
        self._assistant_thinking_cache[msg.id] = current_thinking
        return delta, current_thinking

    def _should_close_thinking_before_text(
        self,
        *,
        message_id: str,
        current_text: str,
        current_thinking: str,
    ) -> bool:
        """判断是否应在文本开始输出前关闭 thinking 流。"""
        return bool(
            current_text
            and current_thinking
            and message_id not in self._closed_thinking_messages
        )

    def _should_close_thinking_on_message_end(
        self,
        *,
        message_id: str,
        current_thinking: str,
        is_last: bool,
    ) -> bool:
        """判断是否应在消息结束时关闭 thinking 流。"""
        return bool(
            is_last
            and current_thinking
            and message_id not in self._closed_thinking_messages
        )

    def _build_tool_call_event(
        self,
        block: ToolUseBlock,
        *,
        is_last: bool,
    ) -> dict[str, Any] | None:
        """在工具输入完整后构造一条 started 状态的工具调用事件。"""
        if not is_last:
            return None

        tool_id = block["id"]
        tool_name = block["name"]
        tool_input = self._resolve_tool_input(block)
        self._tool_name_cache[tool_id] = tool_name
        self._tool_input_cache[tool_id] = tool_input
        payload = {
            "tool_id": tool_id,
            "tool_name": tool_name,
            "status": "started",
            "tool_input": tool_input,
            "output": None,
            "error": None,
            "mcp_name": None,
            "mcp_method": None,
        }
        signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if self._tool_call_cache.get(tool_id) == signature:
            return None
        self._tool_call_cache[tool_id] = signature
        return payload

    def _resolve_tool_input(self, block: ToolUseBlock) -> dict[str, Any]:
        """将原始工具输入规范化为字典载荷。"""
        raw_input = block.get("raw_input")
        if isinstance(raw_input, str) and raw_input.strip():
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                parsed = json.loads(raw_input)
                if isinstance(parsed, dict):
                    return parsed

        input_obj = block.get("input", {})
        return input_obj if isinstance(input_obj, dict) else {}

    def _build_tool_result_event(
        self,
        block: ToolResultBlock,
    ) -> dict[str, Any] | None:
        """在结果尚未发送过时构造一条 completed 状态的工具结果事件。"""
        tool_id = block["id"]
        if tool_id in self._mcp_tool_ids:
            return None

        payload = {
            "tool_id": tool_id,
            "tool_name": block.get("name") or self._tool_name_cache.get(tool_id),
            "status": "completed",
            "tool_input": self._tool_input_cache.get(tool_id),
            "output": normalize_stream_output(block.get("output")),
            "error": None,
            "mcp_name": None,
            "mcp_method": None,
        }
        signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if self._tool_result_cache.get(tool_id) == signature:
            return None
        self._tool_result_cache[tool_id] = signature
        return payload

    def _build_mcp_trace_event(self, block: dict[str, Any]) -> dict[str, Any] | None:
        """将一条 MCP 轨迹块转换为流式工具事件。"""
        tool_id = block.get("tool_id")
        status = block.get("status")
        if not isinstance(tool_id, str):
            return None

        self._mcp_tool_ids.add(tool_id)
        if status == "started":
            return None

        payload = {
            "tool_id": tool_id,
            "tool_name": block.get("tool_name") or self._tool_name_cache.get(tool_id),
            "status": status,
            "tool_input": self._tool_input_cache.get(tool_id),
            "output": normalize_stream_output(block.get("result")),
            "error": block.get("error"),
            "mcp_name": block.get("mcp_name"),
            "mcp_method": block.get("mcp_method"),
        }
        signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if signature in self._mcp_trace_cache:
            return None
        self._mcp_trace_cache.add(signature)
        return payload

"""会话管理模块。

该模块提供：
- 会话创建与状态管理
- 单会话串行执行控制
- SSE 事件流转换
- 中断能力封装
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from agentscope.message import Msg
from agentscope.message._message_block import ToolResultBlock, ToolUseBlock

from app.agent.factory import AgentFactory
from app.agent.mcp_trace import (
    MCP_TRACE_BLOCK_TYPE,
    normalize_stream_output,
)
from app.config import AppConfig
from app.schemas import (
    ChatStreamRequest,
    InterruptResponse,
    ResponseMode,
    SessionStatusResponse,
    TaskResultSchema,
)
from app.tools import PythonSafetyConfig, SafePythonExecutor


class SessionNotFoundError(KeyError):
    """会话不存在异常。"""


class StreamChunkProcessError(RuntimeError):
    """流式块处理异常。

    该异常用于携带出错时的原始消息结构，便于排查流式处理问题。
    """

    def __init__(self, message: str, raw_msg: dict[str, Any] | None = None) -> None:
        """初始化异常对象。

        参数:
            message: 异常描述。
            raw_msg: 出错消息的原始结构。
        """
        super().__init__(message)
        self.raw_msg = raw_msg


@dataclass
class SessionRecord:
    """单个会话的运行时记录。"""

    session_id: str
    agent: Any
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    status: str = "idle"
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    running_task: asyncio.Task | None = None
    last_result: dict[str, Any] | None = None

    def set_status(self, status: str) -> None:
        """更新会话状态并刷新时间戳。

        参数:
            status: 新状态值。

        返回:
            None。
        """
        self.status = status
        self.updated_at = datetime.now(timezone.utc)


class StreamDeduplicator:
    """流式消息去重器。

    该类用于把 AgentScope 消息队列中的累计消息转换为增量 SSE 事件。
    """

    def __init__(self) -> None:
        """初始化去重状态。"""
        self._assistant_text_cache: dict[str, str] = {}
        self._assistant_thinking_cache: dict[str, str] = {}
        self._closed_thinking_messages: set[str] = set()
        self._tool_call_cache: dict[str, str] = {}
        self._tool_result_cache: dict[str, str] = {}
        self._mcp_trace_cache: set[str] = set()
        self._tool_input_cache: dict[str, dict[str, Any]] = {}
        self._tool_name_cache: dict[str, str] = {}
        self._mcp_tool_ids: set[str] = set()

    def extract_events(self, msg: Msg, is_last: bool) -> list[tuple[str, dict[str, Any]]]:
        """从消息中提取 SSE 事件。

        参数:
            msg: AgentScope 消息对象。
            is_last: 当前流式 chunk 是否为最后一块。

        返回:
            list[tuple[str, dict[str, Any]]]: 事件类型与事件载荷的列表。
        """
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
                    ),
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
                    ),
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
                    ),
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
                    ),
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
        """提取 assistant 文本增量。

        参数:
            msg: 消息对象。

        返回:
            tuple[str, str]: 新增文本与当前累计文本。
        """
        current_text = msg.get_text_content(separator="\n") or ""
        previous_text = self._assistant_text_cache.get(msg.id, "")
        if current_text.startswith(previous_text):
            delta = current_text[len(previous_text) :]
        else:
            # 当消息并非简单追加时，回退为整段文本以避免内容丢失。
            delta = current_text
        self._assistant_text_cache[msg.id] = current_text
        return delta, current_text

    def _extract_assistant_thinking_delta(self, msg: Msg) -> tuple[str, str]:
        """提取 assistant thinking 增量。

        参数:
            msg: 消息对象。

        返回:
            tuple[str, str]: 新增 thinking 与当前累计 thinking。
        """
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
        """当正文开始输出时，立即闭合 thinking 流。"""
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
        """仅对没有正文的 assistant 消息在结束时补一个 thinking 收尾。"""
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
        """构建工具调用事件。

        参数:
            block: 工具调用 block。

        返回:
            dict | None: 新工具调用事件，若重复则返回 None。
        """
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
        """提取最终稳定的工具输入参数。"""
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
        """构建工具结果事件。

        参数:
            block: 工具结果 block。

        返回:
            dict | None: 新工具结果事件，若与上次结果一致则返回 None。
        """
        tool_id = block["id"]
        if tool_id in self._mcp_tool_ids:
            return None

        output = normalize_stream_output(block.get("output"))
        payload = {
            "tool_id": tool_id,
            "tool_name": block.get("name") or self._tool_name_cache.get(tool_id),
            "status": "completed",
            "tool_input": self._tool_input_cache.get(tool_id),
            "output": output,
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
        """构建 MCP 调用追踪事件。"""
        status = block.get("status")
        tool_id = block.get("tool_id")
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


class AgentSessionManager:
    """智能体会话管理器。

    对外提供会话创建、状态查询、中断控制和流式聊天四项核心能力。
    """

    def __init__(self, config: AppConfig) -> None:
        """初始化会话管理器。

        参数:
            config: 应用配置对象。
        """
        safety_config = PythonSafetyConfig(
            default_timeout=config.python_tool_timeout,
            max_code_length=config.python_tool_max_code_length,
            max_output_length=config.python_tool_max_output_length,
        )
        python_executor = SafePythonExecutor(safety_config)
        self._factory = AgentFactory(config=config, python_executor=python_executor)
        self._sessions: dict[str, SessionRecord] = {}

    async def create_session(self) -> str:
        """创建新会话。

        返回:
            str: 新会话 ID。
        """
        agent = await self._factory.create_agent()
        session_id = agent.id
        self._sessions[session_id] = SessionRecord(
            session_id=session_id,
            agent=agent,
        )
        return session_id

    def ensure_session_exists(self, session_id: str) -> None:
        """校验会话是否存在。

        参数:
            session_id: 会话 ID。

        返回:
            None。

        异常:
            SessionNotFoundError: 当会话不存在时抛出。
        """
        self._get_session(session_id)

    def get_session_status(self, session_id: str) -> SessionStatusResponse:
        """获取会话状态。

        参数:
            session_id: 会话 ID。

        返回:
            SessionStatusResponse: 当前会话状态。
        """
        session = self._get_session(session_id)
        return SessionStatusResponse(
            session_id=session.session_id,
            status=session.status,
            updated_at=session.updated_at,
            last_result=session.last_result,
        )

    async def interrupt_session(self, session_id: str) -> InterruptResponse:
        """中断会话当前回复任务。

        参数:
            session_id: 会话 ID。

        返回:
            InterruptResponse: 中断执行结果。
        """
        session = self._get_session(session_id)
        if session.running_task is None or session.running_task.done():
            return InterruptResponse(
                session_id=session_id,
                interrupted=False,
                status=session.status,
            )

        await session.agent.interrupt()
        session.set_status("interrupted")
        return InterruptResponse(
            session_id=session_id,
            interrupted=True,
            status=session.status,
        )

    async def stream_chat(
        self,
        session_id: str,
        request: ChatStreamRequest,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行流式聊天并产出 SSE 事件。

        参数:
            session_id: 会话 ID。
            request: 聊天请求体。

        返回:
            AsyncGenerator[dict[str, Any], None]: SSE 事件生成器。
        """
        session = self._get_session(session_id)

        # 会话锁用于保证“同一会话同一时间仅运行一个请求”。
        async with session.lock:
            # 这是状态自愈逻辑：若任务已结束但状态残留为 running，自动修正为 idle。
            self._heal_stale_running_state(session)
            result_msg_raw: dict[str, Any] | None = None

            if session.status == "running":
                yield self._build_event(
                    event_type="error",
                    session_id=session_id,
                    payload={"message": "会话正在运行中，请稍后再试。"},
                )
                return

            queue: asyncio.Queue = asyncio.Queue(maxsize=200)
            session.agent.set_msg_queue_enabled(True, queue=queue)
            session.set_status("running")

            user_msg = Msg(name="user", content=request.message, role="user")
            structured_model = (
                TaskResultSchema
                if request.response_mode == ResponseMode.TASK_RESULT
                else None
            )
            deduplicator = StreamDeduplicator()

            session.running_task = asyncio.create_task(
                self._run_agent_task(
                    session=session,
                    user_msg=user_msg,
                    structured_model=structured_model,
                ),
            )

            try:
                async for event in self._drain_message_queue(
                    session_id=session_id,
                    queue=queue,
                    task=session.running_task,
                    deduplicator=deduplicator,
                ):
                    yield event
                result_msg = await session.running_task
            except asyncio.CancelledError:
                # 当客户端提前断开 SSE 时，主动中断当前 agent 任务并回收状态。
                await self._cleanup_on_stream_cancel(session)
                raise
            except Exception as exc:  # noqa: BLE001 - 需要转为 error 事件
                session.set_status("idle")
                raw_msg = getattr(exc, "raw_msg", None)
                session.last_result = {"error": str(exc), "raw_msg": raw_msg}
                yield self._build_event(
                    event_type="error",
                    session_id=session_id,
                    payload={
                        "message": str(exc),
                        "raw_msg": raw_msg,
                    },
                )
                return
            finally:
                session.running_task = None
                session.agent.set_msg_queue_enabled(False)

            result_metadata = (
                result_msg.metadata
                if isinstance(result_msg.metadata, dict)
                else {}
            )
            is_interrupted = bool(result_metadata.get("_is_interrupted", False))
            if is_interrupted:
                session.set_status("interrupted")
                yield self._build_event(
                    event_type="interrupted",
                    session_id=session_id,
                    payload={
                        "message": result_msg.get_text_content() or "",
                        "metadata": result_msg.metadata,
                    },
                )
            else:
                session.set_status("idle")

            final_payload = {
                "text": result_msg.get_text_content() or "",
                "metadata": result_msg.metadata,
                "response_mode": request.response_mode.value,
            }
            session.last_result = final_payload
            yield self._build_event(
                event_type="final",
                session_id=session_id,
                payload=final_payload,
            )

    async def _run_agent_task(
        self,
        session: SessionRecord,
        user_msg: Msg,
        structured_model: type[TaskResultSchema] | None,
    ) -> Msg:
        """执行智能体回复任务。

        参数:
            session: 会话记录对象。
            user_msg: 用户消息。
            structured_model: 结构化输出模型，可为空。

        返回:
            Msg: 智能体最终回复消息。
        """
        if structured_model is None:
            return await session.agent(user_msg)
        return await session.agent(user_msg, structured_model=structured_model)

    async def _drain_message_queue(
        self,
        session_id: str,
        queue: asyncio.Queue,
        task: asyncio.Task,
        deduplicator: StreamDeduplicator,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """持续消费消息队列并转为 SSE 事件。

        参数:
            session_id: 会话 ID。
            queue: Agent 消息队列。
            task: 正在运行的 agent 任务。
            deduplicator: 流式消息去重器。

        返回:
            AsyncGenerator[dict[str, Any], None]: SSE 事件流。
        """
        while True:
            if task.done() and queue.empty():
                break

            try:
                queued_msg, is_last, _speech = await asyncio.wait_for(
                    queue.get(),
                    timeout=0.2,
                )
            except asyncio.TimeoutError:
                continue

            # 这里是 SSE 事件分发关键路径：将消息按事件类型拆分后逐个输出。
            try:
                extracted_events = deduplicator.extract_events(
                    queued_msg,
                    is_last=is_last,
                )
            except Exception as exc:  # noqa: BLE001 - 需要带出原始消息供调试
                raw_msg = self._serialize_msg_for_debug(queued_msg)
                raise StreamChunkProcessError(
                    message=f"流式块处理失败: {exc}",
                    raw_msg=raw_msg,
                ) from exc

            for event_type, payload in extracted_events:
                yield self._build_event(
                    event_type=event_type,
                    session_id=session_id,
                    payload=payload,
                )

    def _build_event(
        self,
        event_type: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """构建标准 SSE 事件对象。

        参数:
            event_type: 事件类型。
            session_id: 会话 ID。
            payload: 事件载荷。

        返回:
            dict[str, Any]: 标准事件字典。
        """
        return {
            "event_type": event_type,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "payload": payload,
        }

    def _get_session(self, session_id: str) -> SessionRecord:
        """按 ID 获取会话记录。

        参数:
            session_id: 会话 ID。

        返回:
            SessionRecord: 会话记录对象。

        异常:
            SessionNotFoundError: 当会话不存在时抛出。
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"会话不存在: {session_id}")
        return session

    def _heal_stale_running_state(self, session: SessionRecord) -> None:
        """修复残留 running 状态。

        参数:
            session: 会话记录对象。

        返回:
            None。
        """
        if session.status != "running":
            return

        if session.running_task is None:
            session.set_status("idle")
            return

        if session.running_task.done():
            with contextlib.suppress(Exception):
                session.running_task.result()
            session.running_task = None
            session.set_status("idle")

    async def _cleanup_on_stream_cancel(self, session: SessionRecord) -> None:
        """处理 SSE 取消时的会话清理。

        参数:
            session: 会话记录对象。

        返回:
            None。
        """
        if session.running_task is not None and not session.running_task.done():
            await session.agent.interrupt()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(session.running_task, timeout=1.0)
        session.running_task = None
        session.set_status("idle")

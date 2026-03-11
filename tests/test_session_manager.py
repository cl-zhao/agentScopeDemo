"""session_manager 模块单元测试。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from agentscope.message import Msg, TextBlock

from app.agent.session_manager import AgentSessionManager, SessionRecord
from app.config import AppConfig
from app.schemas import ChatStreamRequest, ResponseMode


class FakeAgent:
    """用于测试的最小智能体桩对象。"""

    def __init__(self) -> None:
        """初始化桩对象状态。"""
        self.id = "fake-agent-id"
        self._queue: asyncio.Queue | None = None
        self._interrupted = False

    def set_msg_queue_enabled(self, enabled: bool, queue: asyncio.Queue | None = None) -> None:
        """模拟 AgentScope 消息队列开关行为。

        参数:
            enabled: 是否启用消息队列。
            queue: 指定消息队列实例。

        返回:
            None。
        """
        if enabled:
            self._queue = queue or asyncio.Queue()
        else:
            self._queue = None

    def set_console_output_enabled(self, enabled: bool) -> None:
        """模拟关闭控制台输出。

        参数:
            enabled: 是否启用控制台输出。

        返回:
            None。
        """
        _ = enabled

    async def interrupt(self, msg: Msg | list[Msg] | None = None) -> None:
        """模拟中断行为。

        参数:
            msg: 可选附带消息。

        返回:
            None。
        """
        _ = msg
        self._interrupted = True

    async def __call__(self, *args: Any, **kwargs: Any) -> Msg:
        """模拟智能体回复流程。

        参数:
            *args: 调用参数。
            **kwargs: 调用参数。

        返回:
            Msg: 最终回复消息。
        """
        _ = args
        _ = kwargs
        if self._queue is not None:
            first_msg = Msg(
                name="assistant",
                content=[TextBlock(type="text", text="你好，")],
                role="assistant",
            )
            await self._queue.put((first_msg, False, None))

        for _ in range(20):
            if self._interrupted:
                interrupted_msg = Msg(
                    name="assistant",
                    content=[TextBlock(type="text", text="我已被中断。")],
                    role="assistant",
                    metadata={"_is_interrupted": True},
                )
                if self._queue is not None:
                    await self._queue.put((interrupted_msg, True, None))
                return interrupted_msg
            await asyncio.sleep(0.01)

        final_msg = Msg(
            name="assistant",
            content=[TextBlock(type="text", text="任务完成。")],
            role="assistant",
            metadata={"summary": "ok"},
        )
        if self._queue is not None:
            await self._queue.put((final_msg, True, None))
        return final_msg


def _build_test_config() -> AppConfig:
    """构造测试配置。

    返回:
        AppConfig: 可用于初始化管理器的配置对象。
    """
    return AppConfig(
        ark_api_key="test-key",
        ark_base_url="https://example.com/v1",
        ark_model="test-model",
        model_temperature=0.1,
        model_max_tokens=512,
        python_tool_timeout=2.0,
        python_tool_max_code_length=2000,
        python_tool_max_output_length=2000,
    )


def _replace_session_agent(manager: AgentSessionManager, session_id: str, fake_agent: FakeAgent) -> None:
    """将会话中的真实智能体替换为桩对象。

    参数:
        manager: 会话管理器。
        session_id: 会话 ID。
        fake_agent: 桩智能体。

    返回:
        None。
    """
    manager._sessions[session_id] = SessionRecord(  # noqa: SLF001 - 测试中允许访问内部字段
        session_id=session_id,
        agent=fake_agent,
    )


@pytest.mark.asyncio
async def test_session_status_lifecycle() -> None:
    """测试会话状态在正常流式调用中的生命周期。"""
    manager = AgentSessionManager(config=_build_test_config())
    session_id = manager.create_session()
    _replace_session_agent(manager, session_id, FakeAgent())

    before = manager.get_session_status(session_id)
    assert before.status == "idle"

    events = []
    async for event in manager.stream_chat(
        session_id=session_id,
        request=ChatStreamRequest(message="你好", response_mode=ResponseMode.TEXT),
    ):
        events.append(event)

    after = manager.get_session_status(session_id)
    assert any(evt["event_type"] == "assistant_chunk" for evt in events)
    assert any(evt["event_type"] == "final" for evt in events)
    assert after.status == "idle"


@pytest.mark.asyncio
async def test_session_interrupt_flow() -> None:
    """测试会话中断链路。"""
    manager = AgentSessionManager(config=_build_test_config())
    session_id = manager.create_session()
    _replace_session_agent(manager, session_id, FakeAgent())

    async def _consume_events() -> list[dict]:
        """收集流式事件。

        返回:
            list[dict]: 事件列表。
        """
        collected = []
        async for event in manager.stream_chat(
            session_id=session_id,
            request=ChatStreamRequest(message="请执行长任务", response_mode=ResponseMode.TEXT),
        ):
            collected.append(event)
        return collected

    task = asyncio.create_task(_consume_events())
    await asyncio.sleep(0.05)
    interrupt_result = await manager.interrupt_session(session_id)
    events = await task

    assert interrupt_result.interrupted is True
    assert any(evt["event_type"] == "interrupted" for evt in events)
    status = manager.get_session_status(session_id)
    assert status.status == "interrupted"


@pytest.mark.asyncio
async def test_session_stale_running_state_auto_heal() -> None:
    """测试残留 running 状态自动修复逻辑。"""
    manager = AgentSessionManager(config=_build_test_config())
    session_id = manager.create_session()
    fake_agent = FakeAgent()
    _replace_session_agent(manager, session_id, fake_agent)

    # 构造一个已完成任务，但状态仍为 running 的异常场景。
    done_task = asyncio.create_task(asyncio.sleep(0))
    await done_task
    manager._sessions[session_id].running_task = done_task  # noqa: SLF001 - 测试需要
    manager._sessions[session_id].set_status("running")  # noqa: SLF001 - 测试需要

    events = []
    async for event in manager.stream_chat(
        session_id=session_id,
        request=ChatStreamRequest(message="状态修复后继续对话", response_mode=ResponseMode.TEXT),
    ):
        events.append(event)

    assert any(evt["event_type"] == "final" for evt in events)
    assert manager.get_session_status(session_id).status in {"idle", "interrupted"}


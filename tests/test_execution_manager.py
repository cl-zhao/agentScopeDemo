from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest
from agentscope.message import Msg, TextBlock

from app.config import AppConfig
from app.execution.context_compiler import ContextCompiler
from app.execution.context_package import ContextPackageUpdater
from app.execution.errors import SessionAlreadyRunningError
from app.execution.manager import ExecutionManager
from app.execution.registry import ExecutionRegistry
from app.execution.store import ExecutionStore
from app.schemas import ContextMessage, ContextPackage, ExecutionStreamRequest


class FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    async def set(self, key: str, value: object, ex: int | None = None, nx: bool = False):
        _ = ex
        if nx and key in self._data:
            return False
        self._data[key] = value
        return True

    async def get(self, key: str):
        return self._data.get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                deleted += 1
        return deleted


class FakeAgent:
    def __init__(self, *, slow: bool = False) -> None:
        self.id = "fake-agent"
        self._queue: asyncio.Queue | None = None
        self._interrupted = False
        self._slow = slow

    def set_msg_queue_enabled(self, enabled: bool, queue: asyncio.Queue | None = None) -> None:
        self._queue = queue if enabled else None

    def set_console_output_enabled(self, enabled: bool) -> None:
        _ = enabled

    async def interrupt(self, msg=None) -> None:
        _ = msg
        self._interrupted = True

    async def __call__(self, *args, **kwargs) -> Msg:
        _ = args
        _ = kwargs
        if self._queue is not None:
            await self._queue.put(
                (
                    Msg(
                        name="assistant",
                        role="assistant",
                        content=[TextBlock(type="text", text="partial")],
                    ),
                    False,
                    None,
                )
            )

        for _ in range(20 if self._slow else 1):
            if self._interrupted:
                interrupted = Msg(
                    name="assistant",
                    role="assistant",
                    content=[TextBlock(type="text", text="interrupted")],
                    metadata={"_is_interrupted": True},
                )
                if self._queue is not None:
                    await self._queue.put((interrupted, True, None))
                return interrupted
            await asyncio.sleep(0.01)

        final = Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text="done")],
            metadata={"summary": "ok"},
        )
        if self._queue is not None:
            await self._queue.put((final, True, None))
        return final


class FakeFactory:
    def __init__(self, *, slow: bool = False) -> None:
        self._slow = slow

    async def create_agent(self) -> FakeAgent:
        return FakeAgent(slow=self._slow)


def _build_test_config() -> AppConfig:
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


def build_manager_with_fakes(*, slow: bool = False) -> ExecutionManager:
    config = _build_test_config()
    return ExecutionManager(
        config=config,
        factory=FakeFactory(slow=slow),
        store=ExecutionStore(redis_client=FakeRedis(), key_prefix="ai-engine"),
        registry=ExecutionRegistry(),
        compiler=ContextCompiler(
            recent_message_limit=config.context_recent_message_limit,
            artifact_char_budget=config.context_artifact_char_budget,
        ),
        context_package_updater=ContextPackageUpdater(
            recent_message_limit=config.context_recent_message_limit,
        ),
        instance_name="test-instance",
    )


async def collect_events(stream: AsyncGenerator[dict, None]) -> list[dict]:
    events: list[dict] = []
    async for event in stream:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_stream_execution_emits_started_and_final_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.execution.manager.get_decrypted_principal",
        lambda _token: {"tenant_id": "tenant-1", "user_id": "user-1"},
    )
    manager = build_manager_with_fakes()
    events = []

    async for event in manager.stream_execution(
        ExecutionStreamRequest(
            session_id="session-1",
            access_param="opaque-token",
            context_package=ContextPackage(),
            current_input=ContextMessage(role="user", content="hello"),
        )
    ):
        events.append(event)

    assert events[0]["event_type"] == "execution_started"
    assert events[-1]["event_type"] == "final"


@pytest.mark.asyncio
async def test_stream_execution_rejects_second_active_request_for_same_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.execution.manager.get_decrypted_principal",
        lambda _token: {"tenant_id": "tenant-1", "user_id": "user-1"},
    )
    manager = build_manager_with_fakes(slow=True)

    first = asyncio.create_task(
        collect_events(
            manager.stream_execution(
                ExecutionStreamRequest(
                    session_id="session-1",
                    access_param="opaque-token",
                    context_package=ContextPackage(),
                    current_input=ContextMessage(role="user", content="slow"),
                )
            )
        )
    )
    await asyncio.sleep(0.05)

    with pytest.raises(SessionAlreadyRunningError):
        async for _ in manager.stream_execution(
            ExecutionStreamRequest(
                session_id="session-1",
                access_param="opaque-token",
                context_package=ContextPackage(),
                current_input=ContextMessage(role="user", content="duplicate"),
            )
        ):
            pass

    await first


@pytest.mark.asyncio
async def test_interrupt_execution_marks_result_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.execution.manager.get_decrypted_principal",
        lambda _token: {"tenant_id": "tenant-1", "user_id": "user-1"},
    )
    manager = build_manager_with_fakes(slow=True)

    stream = manager.stream_execution(
        ExecutionStreamRequest(
            session_id="session-1",
            access_param="opaque-token",
            context_package=ContextPackage(),
            current_input=ContextMessage(role="user", content="interrupt me"),
        )
    )

    first_event = await anext(stream)
    interrupt_result = await manager.interrupt_execution(first_event["execution_id"])
    remaining_events = [first_event]
    async for event in stream:
        remaining_events.append(event)

    assert interrupt_result.interrupted is True
    assert any(event["event_type"] == "interrupted" for event in remaining_events)

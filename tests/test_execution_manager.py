from __future__ import annotations

import asyncio
import logging
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
        self.last_request_openai_params: dict[str, object] | None = None
        self.last_request_provider_params: dict[str, object] | None = None

    async def create_agent(
        self,
        request_openai_params: dict[str, object] | None = None,
        request_provider_params: dict[str, object] | None = None,
    ) -> FakeAgent:
        self.last_request_openai_params = request_openai_params
        self.last_request_provider_params = request_provider_params
        agent = FakeAgent(slow=self._slow)
        request_openai_keys = list((request_openai_params or {}).keys())
        request_provider_keys = list((request_provider_params or {}).keys())
        final_extra_body_keys = list(request_provider_keys)
        if request_openai_keys:
            final_extra_body_keys.append("allowed_openai_params")

        param_sources = {
            key: "request_openai" for key in request_openai_keys
        }
        param_sources.update(
            {
                f"extra_body.{key}": "request_provider"
                for key in request_provider_keys
            }
        )
        if request_openai_keys:
            param_sources["extra_body.allowed_openai_params"] = (
                "generated_allowed_openai_passthrough"
            )

        agent._litellm_request_diagnostics = {
            "request_openai_param_keys": request_openai_keys,
            "request_provider_param_keys": request_provider_keys,
            "generated_allowed_openai_param_keys": request_openai_keys,
            "final_top_level_param_keys": [
                "temperature",
                *request_openai_keys,
                *(["extra_body"] if final_extra_body_keys else []),
            ],
            "final_extra_body_keys": final_extra_body_keys,
            "param_sources": param_sources,
        }
        return agent


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
    factory = FakeFactory(slow=slow)
    return ExecutionManager(
        config=config,
        factory=factory,
        store=ExecutionStore(redis_client=FakeRedis(), key_prefix="ai-engine"),
        registry=ExecutionRegistry(),
        compiler=ContextCompiler(
            recent_message_limit=config.context_recent_message_limit,
            artifact_char_budget=config.context_artifact_char_budget,
        ),
        context_package_updater=ContextPackageUpdater(
            recent_message_limit=config.context_recent_message_limit,
            summary_buffer_flush_messages=config.context_summary_buffer_flush_messages,
            summary_buffer_flush_chars=config.context_summary_buffer_flush_chars,
            state_pending_question_limit=config.context_state_pending_question_limit,
            summary_max_items_per_section=config.context_summary_max_items_per_section,
            summary_message_snippet_length=config.context_summary_message_snippet_length,
            summary_max_length=config.context_summary_max_length,
        ),
        instance_name="test-instance",
    )


def build_manager_components_with_fakes(*, slow: bool = False) -> tuple[ExecutionManager, FakeFactory]:
    config = _build_test_config()
    factory = FakeFactory(slow=slow)
    manager = ExecutionManager(
        config=config,
        factory=factory,
        store=ExecutionStore(redis_client=FakeRedis(), key_prefix="ai-engine"),
        registry=ExecutionRegistry(),
        compiler=ContextCompiler(
            recent_message_limit=config.context_recent_message_limit,
            artifact_char_budget=config.context_artifact_char_budget,
        ),
        context_package_updater=ContextPackageUpdater(
            recent_message_limit=config.context_recent_message_limit,
            summary_buffer_flush_messages=config.context_summary_buffer_flush_messages,
            summary_buffer_flush_chars=config.context_summary_buffer_flush_chars,
            state_pending_question_limit=config.context_state_pending_question_limit,
            summary_max_items_per_section=config.context_summary_max_items_per_section,
            summary_message_snippet_length=config.context_summary_message_snippet_length,
            summary_max_length=config.context_summary_max_length,
        ),
        instance_name="test-instance",
    )
    return manager, factory


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


def test_stream_execution_returns_next_context_package_with_memory_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.execution.manager.get_decrypted_principal",
        lambda _token: {"tenant_id": "tenant-1", "user_id": "user-1"},
    )
    manager = build_manager_with_fakes()

    async def _run() -> dict | None:
        final_event = None
        async for event in manager.stream_execution(
            ExecutionStreamRequest(
                session_id="session-1",
                access_param="opaque-token",
                return_context_package=True,
                context_package=ContextPackage(),
                current_input=ContextMessage(role="user", content="hello"),
            )
        ):
            if event["event_type"] == "final":
                final_event = event
        return final_event

    final_event = asyncio.run(_run())

    assert final_event is not None
    next_context_package = final_event["payload"]["next_context_package"]
    assert next_context_package["state"]["facts"] == {}
    assert next_context_package["state"]["task"] == {}
    assert next_context_package["state"]["tool_state"] == {}
    assert next_context_package["state"]["entities"] == {}
    assert next_context_package["memory_meta"]["turn_count"] == 1
    assert next_context_package["memory_meta"]["summary_buffer"] == []


def test_stream_execution_extracts_user_declared_facts_into_next_context_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.execution.manager.get_decrypted_principal",
        lambda _token: {"tenant_id": "tenant-1", "user_id": "user-1"},
    )
    manager = build_manager_with_fakes()

    async def _run() -> dict | None:
        final_event = None
        async for event in manager.stream_execution(
            ExecutionStreamRequest(
                session_id="session-1",
                access_param="opaque-token",
                return_context_package=True,
                context_package=ContextPackage(),
                current_input=ContextMessage(
                    role="user",
                    content="order id is A-1 and tracking number is SF123456789CN",
                ),
            )
        ):
            if event["event_type"] == "final":
                final_event = event
        return final_event

    final_event = asyncio.run(_run())

    assert final_event is not None
    next_context_package = final_event["payload"]["next_context_package"]
    assert next_context_package["state"]["facts"]["order_id"] == "A-1"
    assert next_context_package["state"]["facts"]["tracking_no"] == "SF123456789CN"


def test_stream_execution_flushes_summary_buffer_into_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.execution.manager.get_decrypted_principal",
        lambda _token: {"tenant_id": "tenant-1", "user_id": "user-1"},
    )
    manager = build_manager_with_fakes()

    async def _run() -> dict | None:
        final_event = None
        async for event in manager.stream_execution(
            ExecutionStreamRequest(
                session_id="session-1",
                access_param="opaque-token",
                return_context_package=True,
                context_package=ContextPackage(
                    recent_messages=[
                        ContextMessage(role="user", content="old-user-1"),
                        ContextMessage(role="assistant", content="old-assistant-1"),
                        ContextMessage(role="user", content="old-user-2"),
                        ContextMessage(role="assistant", content="old-assistant-2"),
                        ContextMessage(role="user", content="old-user-3"),
                        ContextMessage(role="assistant", content="old-assistant-3"),
                        ContextMessage(role="user", content="old-user-4"),
                        ContextMessage(role="assistant", content="old-assistant-4"),
                    ],
                    memory_meta={
                        "turn_count": 2,
                        "summary_revision": 0,
                        "last_summary_turn": 0,
                        "summary_buffer": [
                            {"role": "user", "content": "buffered-user"},
                            {"role": "assistant", "content": "buffered-assistant"},
                        ],
                    },
                ),
                current_input=ContextMessage(role="user", content="hello"),
            )
        ):
            if event["event_type"] == "final":
                final_event = event
        return final_event

    final_event = asyncio.run(_run())

    assert final_event is not None
    next_context_package = final_event["payload"]["next_context_package"]
    assert "[背景]" in next_context_package["summary"]
    assert "[已完成事项]" in next_context_package["summary"]
    assert next_context_package["memory_meta"]["summary_buffer"] == []
    assert next_context_package["memory_meta"]["summary_revision"] == 1
    assert next_context_package["memory_meta"]["last_summary_turn"] == 3


def test_stream_execution_passes_split_request_params_to_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.execution.manager.get_decrypted_principal",
        lambda _token: {"tenant_id": "tenant-1", "user_id": "user-1"},
    )
    manager, factory = build_manager_components_with_fakes()

    async def _run() -> None:
        async for _event in manager.stream_execution(
            ExecutionStreamRequest(
                session_id="session-1",
                access_param="opaque-token",
                context_package=ContextPackage(),
                current_input=ContextMessage(role="user", content="hello"),
                openai_params={
                    "parallel_tool_calls": False,
                    "reasoning_effort": "high",
                },
                provider_params={"top_k": 16},
            )
        ):
            pass

    asyncio.run(_run())

    assert factory.last_request_openai_params == {
        "parallel_tool_calls": False,
        "reasoning_effort": "high",
    }
    assert factory.last_request_provider_params == {"top_k": 16}


def test_stream_execution_logs_litellm_request_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "app.execution.manager.get_decrypted_principal",
        lambda _token: {"tenant_id": "tenant-1", "user_id": "user-1"},
    )
    manager, _factory = build_manager_components_with_fakes()
    caplog.set_level(logging.INFO, logger="app.execution.manager")

    async def _run() -> None:
        async for _event in manager.stream_execution(
            ExecutionStreamRequest(
                session_id="session-1",
                access_param="opaque-token",
                context_package=ContextPackage(),
                current_input=ContextMessage(role="user", content="hello"),
                openai_params={
                    "parallel_tool_calls": False,
                    "reasoning_effort": "high",
                },
                provider_params={"top_k": 16},
            )
        ):
            pass

    asyncio.run(_run())

    records = [
        record for record in caplog.records
        if record.msg == "litellm_request_diagnostics"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.session_id == "session-1"
    assert record.model_name == "test-model"
    assert record.request_openai_param_keys == [
        "parallel_tool_calls",
        "reasoning_effort",
    ]
    assert record.request_provider_param_keys == ["top_k"]
    assert record.generated_allowed_openai_param_keys == [
        "parallel_tool_calls",
        "reasoning_effort",
    ]
    assert record.final_top_level_param_keys == [
        "temperature",
        "parallel_tool_calls",
        "reasoning_effort",
        "extra_body",
    ]
    assert record.final_extra_body_keys == ["top_k", "allowed_openai_params"]

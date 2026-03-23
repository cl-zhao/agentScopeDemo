from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from agentscope.message import Msg, TextBlock

from app.agent.session_manager import AgentSessionManager
from app.config import AppConfig
from app.schemas import ChatStreamRequest


class _ContextCapturingAgent:
    def __init__(self) -> None:
        self.id = "capturing-agent"
        self._queue = None
        self.captured_context = None

    def set_msg_queue_enabled(self, enabled: bool, queue=None) -> None:
        self._queue = queue if enabled else None

    def set_console_output_enabled(self, enabled: bool) -> None:
        _ = enabled

    async def interrupt(self, msg=None) -> None:
        _ = msg

    async def __call__(self, *args, **kwargs) -> Msg:
        _ = args
        _ = kwargs
        from app.agent.litellm_context import get_current_litellm_request_context

        self.captured_context = get_current_litellm_request_context()
        reply = Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text="done")],
            metadata={"summary": "ok"},
        )
        if self._queue is not None:
            await self._queue.put((reply, True, None))
        return reply


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


@pytest.mark.asyncio
async def test_context_aware_openai_model_injects_litellm_usage_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, object] = {}

    class _FakeCompletions:
        async def create(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(choices=[], usage=None)

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            _ = args
            _ = kwargs
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setattr("openai.AsyncClient", _FakeAsyncClient)

    from app.agent.litellm_context import (
        ContextAwareOpenAIChatModel,
        LiteLLMRequestContext,
        reset_current_litellm_request_context,
        set_current_litellm_request_context,
    )

    model = ContextAwareOpenAIChatModel(
        model_name="demo-model",
        api_key="sk-test",
        stream=False,
        client_kwargs={"base_url": "http://localhost:4000/v1"},
        generate_kwargs={"temperature": 0.2},
    )
    context = LiteLLMRequestContext(
        tenant_id="tenant-1",
        user_id="user-9",
        end_user_id="tenant-1:user-9",
        app_request_id="app-request-1",
        agentscope_session_id="session-123",
    )

    token = set_current_litellm_request_context(context)
    try:
        await model(
            [{"role": "user", "content": "hello"}],
            metadata={"source": "test"},
        )
    finally:
        reset_current_litellm_request_context(token)

    assert recorded["user"] == "tenant-1:user-9"
    assert recorded["extra_headers"] == {
        "x-end-user-id": "tenant-1:user-9",
        "x-litellm-session-id": "session-123",
    }
    assert recorded["metadata"] == {
        "source": "test",
        "tenant_id": "tenant-1",
        "user_id": "user-9",
        "app_request_id": "app-request-1",
        "agentscope_session_id": "session-123",
    }


@pytest.mark.asyncio
async def test_stream_chat_sets_litellm_request_context_from_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = AgentSessionManager(config=_build_test_config())
    fake_agent = _ContextCapturingAgent()

    async def _create_agent() -> _ContextCapturingAgent:
        return fake_agent

    manager._factory.create_agent = _create_agent  # type: ignore[method-assign]  # noqa: SLF001
    session_id = await manager.create_session()

    monkeypatch.setattr(
        "app.agent.session_manager.get_decrypted_principal",
        lambda _token: {
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier": "user-9",
            "http://www.aspnetboilerplate.com/identity/claims/tenantId": "tenant-1",
        },
    )

    events = []
    async for event in manager.stream_chat(
        session_id=session_id,
        request=ChatStreamRequest(message="hello", access_param="opaque-token"),
    ):
        events.append(event)

    assert fake_agent.captured_context is not None
    assert fake_agent.captured_context.tenant_id == "tenant-1"
    assert fake_agent.captured_context.user_id == "user-9"
    assert fake_agent.captured_context.end_user_id == "tenant-1:user-9"
    assert fake_agent.captured_context.agentscope_session_id == session_id
    UUID(fake_agent.captured_context.app_request_id)
    assert any(event["event_type"] == "final" for event in events)

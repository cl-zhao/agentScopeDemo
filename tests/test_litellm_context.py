from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.litellm_context import (
    ContextAwareOpenAIChatModel,
    LiteLLMRequestContext,
    build_litellm_request_context,
    reset_current_litellm_request_context,
    set_current_litellm_request_context,
)


def test_build_litellm_request_context_contains_execution_id() -> None:
    context = build_litellm_request_context(
        {"tenant_id": "tenant-1", "user_id": "user-1"},
        session_id="session-1",
        execution_id="exec-1",
        app_request_id="request-1",
    )

    assert context.execution_id == "exec-1"
    assert context.agentscope_session_id == "session-1"


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
        execution_id="exec-123",
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
        "execution_id": "exec-123",
    }

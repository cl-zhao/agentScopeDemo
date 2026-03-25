"""Execution API integration tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi.testclient import TestClient

from app.config import AppConfig, ModelRequestConfig
from app.main import create_app
from app.schemas import (
    ExecutionInterruptResponse,
    ExecutionResponse,
    ExecutionStatusResponse,
    ExecutionStreamRequest,
)


class FakeExecutionManager:
    def __init__(self) -> None:
        self._execution_id = "exec-1"
        self._session_id = "session-1"

    async def stream_execution(
        self,
        request: ExecutionStreamRequest,
    ) -> AsyncGenerator[dict, None]:
        yield {
            "event_type": "execution_started",
            "execution_id": self._execution_id,
            "session_id": request.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"status": "running"},
        }
        yield {
            "event_type": "final",
            "execution_id": self._execution_id,
            "session_id": request.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"text": "done", "metadata": {}, "response_mode": "text"},
        }

    async def run_execution(self, request: ExecutionStreamRequest) -> ExecutionResponse:
        return ExecutionResponse(
            execution_id=self._execution_id,
            session_id=request.session_id,
            status="completed",
            text="done",
            metadata={},
            response_mode="text",
        )

    async def get_execution_status(self, execution_id: str) -> ExecutionStatusResponse:
        return ExecutionStatusResponse(
            execution_id=execution_id,
            session_id=self._session_id,
            status="completed",
            started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            last_error=None,
        )

    async def interrupt_execution(self, execution_id: str) -> ExecutionInterruptResponse:
        return ExecutionInterruptResponse(
            execution_id=execution_id,
            interrupted=True,
            status="interrupted",
        )

    async def interrupt_session(self, session_id: str) -> ExecutionInterruptResponse:
        _ = session_id
        return ExecutionInterruptResponse(
            execution_id=self._execution_id,
            interrupted=True,
            status="interrupted",
        )


def _extract_sse_events(raw_text: str) -> list[dict]:
    events = []
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_stream_execution_endpoint() -> None:
    app = create_app(execution_manager=FakeExecutionManager())
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/executions/stream",
        json={
            "session_id": "session-1",
            "access_param": "opaque-token",
            "context_package": {"version": "1.0"},
            "current_input": {"role": "user", "content": "hello"},
        },
    ) as response:
        body_text = "".join(response.iter_text())

    events = _extract_sse_events(body_text)
    assert response.status_code == 200
    assert events[0]["event_type"] == "execution_started"
    assert events[-1]["event_type"] == "final"


def test_stream_execution_rejects_reserved_allowed_openai_param_keys() -> None:
    app = create_app(
        execution_manager=FakeExecutionManager(),
        config=AppConfig(
            ark_api_key="sk-test",
            ark_base_url="http://localhost:4000/v1",
            ark_model="demo-model",
            model_request_config=ModelRequestConfig(
                non_overridable_request_params=["model", "messages"],
            ),
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/executions/stream",
        json={
            "session_id": "session-1",
            "access_param": "opaque-token",
            "context_package": {"version": "1.0"},
            "current_input": {"role": "user", "content": "hello"},
            "allowed_openai_params": {"model": "override-model"},
        },
    )

    assert response.status_code == 400
    assert "allowed_openai_params" in response.json()["detail"]


def test_interrupt_by_execution_id_endpoint() -> None:
    app = create_app(execution_manager=FakeExecutionManager())
    client = TestClient(app)

    response = client.post("/v1/executions/exec-1/interrupt")

    assert response.status_code == 200
    assert response.json()["execution_id"] == "exec-1"


def test_compat_session_interrupt_endpoint_maps_to_active_execution() -> None:
    app = create_app(execution_manager=FakeExecutionManager())
    client = TestClient(app)

    response = client.post("/v1/sessions/session-1/interrupt")

    assert response.status_code == 200
    assert response.json()["execution_id"] == "exec-1"

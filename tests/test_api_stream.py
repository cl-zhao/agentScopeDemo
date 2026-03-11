"""API 路由集成测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import (
    ChatStreamRequest,
    InterruptResponse,
    SessionStatusResponse,
)


class FakeApiManager:
    """用于 API 测试的会话管理器桩对象。"""

    def __init__(self) -> None:
        """初始化桩对象状态。"""
        self._session_id = "session-test-1"

    def create_session(self) -> str:
        """模拟创建会话。"""
        return self._session_id

    def ensure_session_exists(self, session_id: str) -> None:
        """模拟会话存在性检查。"""
        if session_id != self._session_id:
            raise KeyError("会话不存在")

    def get_session_status(self, session_id: str) -> SessionStatusResponse:
        """模拟状态查询。"""
        self.ensure_session_exists(session_id)
        return SessionStatusResponse(
            session_id=session_id,
            status="idle",
            updated_at=datetime.now(timezone.utc),
            last_result={"text": "ok"},
        )

    async def interrupt_session(self, session_id: str) -> InterruptResponse:
        """模拟中断请求。"""
        self.ensure_session_exists(session_id)
        return InterruptResponse(
            session_id=session_id,
            interrupted=True,
            status="interrupted",
        )

    async def stream_chat(
        self,
        session_id: str,
        request: ChatStreamRequest,
    ) -> AsyncGenerator[dict, None]:
        """模拟内部流式事件。"""
        self.ensure_session_exists(session_id)
        yield {
            "event_type": "thinking_chunk",
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"thinking": "先思考一下", "is_last": False},
        }
        yield {
            "event_type": "assistant_chunk",
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"text": f"echo: {request.message}", "is_last": False},
        }
        yield {
            "event_type": "final",
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"text": "done", "metadata": {}, "response_mode": "text"},
        }


def _extract_sse_events(raw_text: str) -> list[dict]:
    """解析 SSE 响应体中的 data 行。"""
    events = []
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_create_session_endpoint() -> None:
    """测试创建会话接口。"""
    app = create_app()
    app.state.session_manager = FakeApiManager()
    client = TestClient(app)

    response = client.post("/v1/sessions")
    assert response.status_code == 200
    assert response.json()["session_id"] == "session-test-1"


def test_chat_stream_endpoint() -> None:
    """测试流式聊天接口透传原始事件格式。"""
    app = create_app()
    app.state.session_manager = FakeApiManager()
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/sessions/session-test-1/chat/stream",
        json={"message": "hello"},
    ) as response:
        body_text = "".join(response.iter_text())

    events = _extract_sse_events(body_text)
    assert response.status_code == 200
    assert len(events) == 3
    assert events[0]["event_type"] == "thinking_chunk"
    assert events[0]["payload"]["thinking"] == "先思考一下"
    assert events[0]["payload"]["is_last"] is False
    assert events[1]["event_type"] == "assistant_chunk"
    assert events[1]["payload"]["text"] == "echo: hello"
    assert events[1]["payload"]["is_last"] is False
    assert events[2]["event_type"] == "final"
    assert events[2]["payload"]["text"] == "done"
    assert events[2]["payload"]["response_mode"] == "text"


def test_interrupt_and_status_endpoint() -> None:
    """测试中断与状态查询接口。"""
    app = create_app()
    app.state.session_manager = FakeApiManager()
    client = TestClient(app)

    interrupt_response = client.post("/v1/sessions/session-test-1/interrupt")
    status_response = client.get("/v1/sessions/session-test-1")

    assert interrupt_response.status_code == 200
    assert interrupt_response.json()["interrupted"] is True
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "idle"

"""Schema unit tests."""

from __future__ import annotations

from app.schemas import (
    ChatStreamRequest,
    ContextArtifact,
    ContextMessage,
    ContextPackage,
    ExecutionStreamRequest,
    ResponseMode,
    TaskResultSchema,
)


def test_chat_stream_request_default_mode() -> None:
    request = ChatStreamRequest(message="hello", access_param="opaque-token")
    assert request.response_mode == ResponseMode.TEXT


def test_task_result_schema_fields() -> None:
    result = TaskResultSchema(
        summary="task complete",
        actions=["action-1"],
        risks=["risk-1"],
        next_steps=["next-step-1"],
    )
    dumped = result.model_dump()
    assert dumped["summary"] == "task complete"
    assert dumped["actions"] == ["action-1"]
    assert dumped["risks"] == ["risk-1"]
    assert dumped["next_steps"] == ["next-step-1"]


def test_execution_stream_request_defaults() -> None:
    request = ExecutionStreamRequest(
        session_id="biz-session-1",
        access_param="opaque-token",
        context_package=ContextPackage(),
        current_input=ContextMessage(role="user", content="hello"),
    )

    assert request.return_context_package is False
    assert request.response_mode == ResponseMode.TEXT
    assert request.context_package.version == "1.0"


def test_context_package_accepts_artifacts_and_state() -> None:
    package = ContextPackage(
        summary="older summary",
        state={"facts": {"order_id": "A-1"}},
        recent_messages=[ContextMessage(role="assistant", content="done")],
        artifacts=[
            ContextArtifact(
                id="tool-1",
                type="tool_result",
                tool_name="execute_sql_query",
                content={"rows": [{"id": 1}]},
                importance="high",
            )
        ],
    )

    assert package.state["facts"]["order_id"] == "A-1"
    assert package.artifacts[0].tool_name == "execute_sql_query"


def test_context_package_defaults_memory_meta() -> None:
    package = ContextPackage()

    assert package.memory_meta.turn_count == 0
    assert package.memory_meta.summary_revision == 0
    assert package.memory_meta.last_summary_turn == 0
    assert package.memory_meta.summary_buffer == []

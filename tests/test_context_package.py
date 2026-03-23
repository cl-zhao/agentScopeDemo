from __future__ import annotations

from app.execution.context_package import ContextPackageUpdater, build_tool_artifact
from app.schemas import ContextMessage, ContextPackage


def test_build_next_context_package_appends_latest_turn() -> None:
    updater = ContextPackageUpdater(recent_message_limit=4)
    next_package = updater.build_next_package(
        previous=ContextPackage(
            summary="older summary",
            recent_messages=[ContextMessage(role="user", content="old question")],
        ),
        current_input=ContextMessage(role="user", content="new question"),
        final_text="new answer",
        artifacts=[],
    )

    assert next_package.recent_messages[-2].content == "new question"
    assert next_package.recent_messages[-1].content == "new answer"


def test_build_artifacts_keeps_raw_tool_output() -> None:
    artifact = build_tool_artifact(
        tool_event={
            "tool_id": "tool-1",
            "tool_name": "execute_sql_query",
            "status": "completed",
            "output": [{"type": "text", "text": "{\"rows\":[{\"id\":1}]}"}],
        }
    )

    assert artifact.tool_name == "execute_sql_query"
    assert artifact.content[0]["text"].startswith("{\"rows\"")

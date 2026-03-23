from __future__ import annotations

from app.execution.context_compiler import ContextCompiler
from app.schemas import ContextArtifact, ContextMessage, ContextPackage


def test_compiler_prioritizes_current_input_and_recent_messages() -> None:
    compiler = ContextCompiler(recent_message_limit=3, artifact_char_budget=120)
    compiled = compiler.compile(
        context_package=ContextPackage(
            summary="older summary",
            state={"facts": {"order_id": "A-1"}},
            recent_messages=[
                ContextMessage(role="user", content="first"),
                ContextMessage(role="assistant", content="second"),
            ],
        ),
        current_input=ContextMessage(role="user", content="where is my order?"),
    )

    assert "CURRENT_INPUT" in compiled.prompt_text
    assert "where is my order?" in compiled.prompt_text
    assert "order_id" in compiled.prompt_text


def test_compiler_drops_low_priority_artifacts_when_budget_is_small() -> None:
    compiler = ContextCompiler(recent_message_limit=3, artifact_char_budget=20)
    compiled = compiler.compile(
        context_package=ContextPackage(
            artifacts=[
                ContextArtifact(
                    id="a",
                    type="tool_result",
                    tool_name="x",
                    content="1234567890",
                    importance="high",
                ),
                ContextArtifact(
                    id="b",
                    type="tool_result",
                    tool_name="y",
                    content="abcdefghij",
                    importance="low",
                ),
            ]
        ),
        current_input=ContextMessage(role="user", content="hello"),
    )

    assert "1234567890" in compiled.prompt_text
    assert "abcdefghij" not in compiled.prompt_text

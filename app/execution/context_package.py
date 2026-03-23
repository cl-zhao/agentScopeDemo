"""Helpers for building updated caller-managed context packages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas import ContextArtifact, ContextMessage, ContextPackage


def build_tool_artifact(tool_event: dict[str, Any]) -> ContextArtifact:
    """Convert one completed tool event into a raw artifact entry."""

    return ContextArtifact(
        id=str(tool_event["tool_id"]),
        type="tool_result",
        tool_name=tool_event.get("tool_name"),
        # Preserve raw output exactly as emitted so the caller can decide later
        # how aggressively to trim or normalize historical artifacts.
        content=tool_event.get("output"),
        importance="high" if tool_event.get("status") == "completed" else "medium",
        created_at=datetime.now(timezone.utc),
    )


class ContextPackageUpdater:
    """Builds the optional next context package returned to the caller."""

    def __init__(self, *, recent_message_limit: int) -> None:
        self._recent_message_limit = recent_message_limit

    def build_next_package(
        self,
        *,
        previous: ContextPackage,
        current_input: ContextMessage,
        final_text: str,
        artifacts: list[ContextArtifact],
    ) -> ContextPackage:
        # Keep the most recent dialogue window only; long-range continuity stays
        # in `summary` and `state`, which are caller-managed.
        recent_messages = [
            *previous.recent_messages,
            current_input,
            ContextMessage(role="assistant", content=final_text),
        ][-self._recent_message_limit :]

        return ContextPackage(
            version=previous.version,
            summary=previous.summary,
            state=dict(previous.state),
            recent_messages=recent_messages,
            artifacts=[*previous.artifacts, *artifacts],
        )

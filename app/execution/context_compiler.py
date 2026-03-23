"""Deterministic context compilation for stateless executions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.schemas import ContextArtifact, ContextMessage, ContextPackage


@dataclass
class CompiledContext:
    """Compiled prompt text plus compilation metadata."""

    prompt_text: str
    included_artifact_ids: list[str] = field(default_factory=list)
    dropped_artifact_ids: list[str] = field(default_factory=list)


class ContextCompiler:
    """Builds one deterministic prompt from a caller-managed context package."""

    def __init__(self, *, recent_message_limit: int, artifact_char_budget: int) -> None:
        self._recent_message_limit = recent_message_limit
        self._artifact_char_budget = artifact_char_budget

    def compile(
        self,
        *,
        context_package: ContextPackage,
        current_input: ContextMessage,
    ) -> CompiledContext:
        included_artifact_ids: list[str] = []
        dropped_artifact_ids: list[str] = []

        recent_messages = context_package.recent_messages[-self._recent_message_limit :]
        artifact_lines, included_artifact_ids, dropped_artifact_ids = self._select_artifacts(
            context_package.artifacts,
        )

        sections = [
            ("SUMMARY", context_package.summary.strip()),
            ("STATE", self._format_state(context_package.state)),
            ("RECENT_MESSAGES", self._format_recent_messages(recent_messages)),
            ("ARTIFACTS", "\n".join(artifact_lines)),
            ("CURRENT_INPUT", current_input.content.strip()),
        ]

        prompt_text = "\n\n".join(
            f"{title}:\n{body}"
            for title, body in sections
            if body
        )

        return CompiledContext(
            prompt_text=prompt_text,
            included_artifact_ids=included_artifact_ids,
            dropped_artifact_ids=dropped_artifact_ids,
        )

    def _format_state(self, state: dict) -> str:
        if not state:
            return ""
        return json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)

    def _format_recent_messages(self, messages: list[ContextMessage]) -> str:
        if not messages:
            return ""
        return "\n".join(f"- {message.role}: {message.content}" for message in messages)

    def _select_artifacts(
        self,
        artifacts: list[ContextArtifact],
    ) -> tuple[list[str], list[str], list[str]]:
        if not artifacts:
            return [], [], []

        remaining_budget = self._artifact_char_budget
        included_lines: list[str] = []
        included_ids: list[str] = []
        dropped_ids: list[str] = []

        # High-value artifacts must win under pressure, so selection is ordered by
        # importance first and original position second for determinism.
        ranked = sorted(
            enumerate(artifacts),
            key=lambda item: (self._artifact_rank(item[1].importance), item[0]),
        )

        for _index, artifact in ranked:
            line = self._format_artifact(artifact)
            line_cost = len(line)
            # Once the artifact budget is exhausted we still keep recording drops so
            # callers can observe what was trimmed out of the compiled context.
            if line_cost > remaining_budget:
                dropped_ids.append(artifact.id)
                continue
            included_lines.append(line)
            included_ids.append(artifact.id)
            remaining_budget -= line_cost

        return included_lines, included_ids, dropped_ids

    def _format_artifact(self, artifact: ContextArtifact) -> str:
        payload = artifact.content
        if isinstance(payload, str):
            rendered_content = payload
        else:
            rendered_content = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        tool_label = artifact.tool_name or artifact.type
        return f"- {artifact.id} [{tool_label}] {rendered_content}"

    @staticmethod
    def _artifact_rank(importance: str) -> int:
        order = {"high": 0, "medium": 1, "low": 2}
        return order.get(importance, 3)

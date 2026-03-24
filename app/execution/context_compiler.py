"""无状态执行的确定性上下文编译器。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.schemas import ContextArtifact, ContextMessage, ContextPackage


@dataclass
class CompiledContext:
    """编译后的提示词文本及其元数据。"""

    prompt_text: str
    included_artifact_ids: list[str] = field(default_factory=list)
    dropped_artifact_ids: list[str] = field(default_factory=list)


class ContextCompiler:
    """根据调用方维护的上下文包构建确定性提示词。"""

    def __init__(self, *, recent_message_limit: int, artifact_char_budget: int) -> None:
        """保存最近消息和 artifacts 的编译限制。"""
        self._recent_message_limit = recent_message_limit
        self._artifact_char_budget = artifact_char_budget

    def compile(
        self,
        *,
        context_package: ContextPackage,
        current_input: ContextMessage,
    ) -> CompiledContext:
        """将调用方维护的上下文包编译为提示词载荷。"""
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
        """将结构化状态渲染为确定性的格式化 JSON。"""
        if not state:
            return ""
        return json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)

    def _format_recent_messages(self, messages: list[ContextMessage]) -> str:
        """以带角色前缀的简单列表格式渲染最近消息。"""
        if not messages:
            return ""
        return "\n".join(f"- {message.role}: {message.content}" for message in messages)

    def _select_artifacts(
        self,
        artifacts: list[ContextArtifact],
    ) -> tuple[list[str], list[str], list[str]]:
        """在预算内选择 artifacts，并记录被确定性裁掉的条目。"""
        if not artifacts:
            return [], [], []

        remaining_budget = self._artifact_char_budget
        included_lines: list[str] = []
        included_ids: list[str] = []
        dropped_ids: list[str] = []

        # 预算紧张时高价值 artifact 必须优先保留，因此先按重要度、再按原始顺序排序。
        ranked = sorted(
            enumerate(artifacts),
            key=lambda item: (self._artifact_rank(item[1].importance), item[0]),
        )

        for _index, artifact in ranked:
            line = self._format_artifact(artifact)
            line_cost = len(line)
            # 即使预算已经耗尽，也继续记录被裁掉的条目，方便调用方观测裁剪结果。
            if line_cost > remaining_budget:
                dropped_ids.append(artifact.id)
                continue
            included_lines.append(line)
            included_ids.append(artifact.id)
            remaining_budget -= line_cost

        return included_lines, included_ids, dropped_ids

    def _format_artifact(self, artifact: ContextArtifact) -> str:
        """将单个 artifact 渲染为一行提示词文本。"""
        payload = artifact.content
        if isinstance(payload, str):
            rendered_content = payload
        else:
            rendered_content = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        tool_label = artifact.tool_name or artifact.type
        return f"- {artifact.id} [{tool_label}] {rendered_content}"

    @staticmethod
    def _artifact_rank(importance: str) -> int:
        """将文本形式的重要度映射为确定性的排序权重。"""
        order = {"high": 0, "medium": 1, "low": 2}
        return order.get(importance, 3)

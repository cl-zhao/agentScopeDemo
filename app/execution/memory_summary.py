"""用于较早对话记忆的确定性摘要压缩辅助工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas import ContextMessage

_SUMMARY_SECTION_ORDER = ("背景", "已确认事实", "已完成事项", "未决事项")


@dataclass
class SummaryCompressionResult:
    """摘要压缩结果。"""

    summary: str
    changed: bool


class SummaryCompressor:
    """根据缓冲的旧消息构建分段滚动摘要。"""

    def __init__(
        self,
        *,
        max_items_per_section: int,
        message_snippet_length: int,
        max_summary_length: int,
    ) -> None:
        """保存确定性摘要压缩所需的格式限制。"""
        self._max_items_per_section = max_items_per_section
        self._message_snippet_length = message_snippet_length
        self._max_summary_length = max_summary_length

    def compress(
        self,
        *,
        previous_summary: str,
        flush_messages: list[ContextMessage],
        state_delta: dict[str, Any],
    ) -> SummaryCompressionResult:
        """将缓冲旧消息和新的状态增量折叠进滚动摘要。"""
        sections = self._parse_summary(previous_summary)
        for message in flush_messages:
            if message.role == "user":
                self._append_item(sections["背景"], f"用户提到：{self._snippet(message.content)}")
            elif message.role == "assistant":
                self._append_item(sections["已完成事项"], f"已回复：{self._snippet(message.content)}")

        for fact_key, fact_value in sorted(self._flatten_section(state_delta.get("facts", {})).items()):
            self._append_item(sections["已确认事实"], f"{fact_key}: {fact_value}")

        pending_questions = state_delta.get("task", {}).get("pending_questions")
        if isinstance(pending_questions, list):
            for question in pending_questions:
                if isinstance(question, str) and question.strip():
                    self._append_item(sections["未决事项"], question.strip())

        rendered_summary = self._render_summary(sections)
        if len(rendered_summary) > self._max_summary_length:
            rendered_summary = rendered_summary[: self._max_summary_length - 3].rstrip() + "..."
        return SummaryCompressionResult(
            summary=rendered_summary,
            changed=rendered_summary != previous_summary,
        )

    def _parse_summary(self, summary: str) -> dict[str, list[str]]:
        """将已有摘要解析回分区条目列表。"""
        sections = {section_name: [] for section_name in _SUMMARY_SECTION_ORDER}
        current_section = "背景"
        for raw_line in summary.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                header = line[1:-1].strip()
                if header in sections:
                    current_section = header
                continue
            item = line[2:].strip() if line.startswith("- ") else line
            if item:
                self._append_item(sections[current_section], item)
        return sections

    def _render_summary(self, sections: dict[str, list[str]]) -> str:
        """将分区条目重新渲染为持久化摘要文本。"""
        blocks: list[str] = []
        for section_name in _SUMMARY_SECTION_ORDER:
            items = self._trim_items(sections[section_name])
            if not items:
                continue
            block_lines = [f"[{section_name}]"]
            block_lines.extend(f"- {item}" for item in items)
            blocks.append("\n".join(block_lines))
        return "\n\n".join(blocks)

    def _append_item(self, section_items: list[str], item: str) -> None:
        """向摘要分区追加一条唯一条目。"""
        if item not in section_items:
            section_items.append(item)

    def _trim_items(self, items: list[str]) -> list[str]:
        """将摘要分区裁剪到配置的尾部条目上限。"""
        if len(items) <= self._max_items_per_section:
            return items
        return items[-self._max_items_per_section :]

    def _snippet(self, text: str) -> str:
        """在写入摘要前规范化并截短消息文本。"""
        normalized = " ".join(text.split())
        if len(normalized) <= self._message_snippet_length:
            return normalized
        return normalized[: self._message_snippet_length - 3].rstrip() + "..."

    def _flatten_section(self, payload: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """将嵌套摘要增量数据拍平成点分键值对。"""
        flattened: dict[str, Any] = {}
        for key, value in payload.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                flattened.update(self._flatten_section(value, prefix=full_key))
            elif isinstance(value, list):
                flattened[full_key] = ", ".join(str(item) for item in value)
            else:
                flattened[full_key] = value
        return flattened

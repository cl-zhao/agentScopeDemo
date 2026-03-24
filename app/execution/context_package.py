"""用于构建更新后调用方上下文包的辅助工具。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.execution.memory_state import (
    StateObservationExtractor,
    StateReducer,
    normalize_context_state,
)
from app.execution.memory_summary import SummaryCompressor
from app.execution.memory_window import RecentMessageWindowManager, SummaryBufferManager
from app.schemas import ContextArtifact, ContextMemoryMeta, ContextMessage, ContextPackage


def build_tool_artifact(tool_event: dict[str, Any]) -> ContextArtifact:
    """将单个已完成的工具事件转换为原始 artifact 条目。"""

    return ContextArtifact(
        id=str(tool_event["tool_id"]),
        type="tool_result",
        tool_name=tool_event.get("tool_name"),
        # 保留工具原始输出，后续由调用方自行决定是否裁剪或规范化历史 artifact。
        content=tool_event.get("output"),
        importance="high" if tool_event.get("status") == "completed" else "medium",
        created_at=datetime.now(timezone.utc),
    )


class ContextPackageUpdater:
    """构建可选返回给调用方的下一份上下文包。"""

    def __init__(
        self,
        *,
        recent_message_limit: int,
        summary_buffer_flush_messages: int,
        summary_buffer_flush_chars: int,
        state_pending_question_limit: int = 6,
        summary_max_items_per_section: int = 6,
        summary_message_snippet_length: int = 120,
        summary_max_length: int = 2000,
        observation_extractor: StateObservationExtractor | None = None,
        state_reducer: StateReducer | None = None,
        recent_window_manager: RecentMessageWindowManager | None = None,
        summary_buffer_manager: SummaryBufferManager | None = None,
        summary_compressor: SummaryCompressor | None = None,
    ) -> None:
        """构造确定性的上下文更新流水线及其限制参数。"""
        self._observation_extractor = observation_extractor or StateObservationExtractor()
        self._state_reducer = state_reducer or StateReducer(
            pending_question_limit=state_pending_question_limit,
        )
        self._recent_window_manager = recent_window_manager or RecentMessageWindowManager(
            recent_message_limit=recent_message_limit,
        )
        self._summary_buffer_manager = summary_buffer_manager or SummaryBufferManager(
            flush_message_count=summary_buffer_flush_messages,
            flush_char_count=summary_buffer_flush_chars,
        )
        self._summary_compressor = summary_compressor or SummaryCompressor(
            max_items_per_section=summary_max_items_per_section,
            message_snippet_length=summary_message_snippet_length,
            max_summary_length=summary_max_length,
        )

    def build_next_package(
        self,
        *,
        previous: ContextPackage,
        current_input: ContextMessage,
        final_text: str,
        artifacts: list[ContextArtifact],
    ) -> ContextPackage:
        """在一次执行完成后构建新的调用方上下文包。"""
        previous_state = normalize_context_state(previous.state)
        observations = self._observation_extractor.extract(
            current_input=current_input,
            final_text=final_text,
            new_artifacts=artifacts,
        )
        reduce_result = self._state_reducer.reduce(
            previous_state=previous_state,
            observations=observations,
        )
        recent_window = self._recent_window_manager.update(
            previous_messages=previous.recent_messages,
            current_input=current_input,
            final_text=final_text,
        )
        next_turn_count = previous.memory_meta.turn_count + 1
        buffer_decision = self._summary_buffer_manager.update(
            previous_buffer=previous.memory_meta.summary_buffer,
            evicted_messages=recent_window.evicted_messages,
        )
        next_summary = previous.summary
        next_summary_revision = previous.memory_meta.summary_revision
        next_last_summary_turn = previous.memory_meta.last_summary_turn
        next_summary_buffer = buffer_decision.next_buffer

        if buffer_decision.should_flush:
            try:
                compression_result = self._summary_compressor.compress(
                    previous_summary=previous.summary,
                    flush_messages=buffer_decision.flush_messages,
                    state_delta=reduce_result.state_delta,
                )
            except Exception:  # noqa: BLE001 - 摘要压缩失败时回退到上一版本摘要
                compression_result = None
            if compression_result is not None and compression_result.changed:
                next_summary = compression_result.summary
                next_summary_revision += 1
                next_last_summary_turn = next_turn_count
                next_summary_buffer = []

        return ContextPackage(
            version=previous.version,
            summary=next_summary,
            state=reduce_result.next_state,
            recent_messages=recent_window.recent_messages,
            artifacts=[*previous.artifacts, *artifacts],
            memory_meta=ContextMemoryMeta(
                turn_count=next_turn_count,
                summary_revision=next_summary_revision,
                last_summary_turn=next_last_summary_turn,
                summary_buffer=next_summary_buffer,
            ),
        )

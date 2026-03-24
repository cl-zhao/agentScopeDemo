"""最近消息窗口与摘要缓冲区辅助工具。"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import ContextMessage


@dataclass
class RecentWindowResult:
    """最新最近消息窗口，以及从窗口中挤出的消息。"""

    recent_messages: list[ContextMessage]
    evicted_messages: list[ContextMessage]


@dataclass
class SummaryBufferDecision:
    """将新挤出的消息并入摘要缓冲区后的决策结果。"""

    next_buffer: list[ContextMessage]
    should_flush: bool
    flush_messages: list[ContextMessage]
    reason: str


class RecentMessageWindowManager:
    """维护有上限的最新高保真消息列表。"""

    def __init__(self, *, recent_message_limit: int) -> None:
        """保存最近消息按原文保留的最大条数。"""
        self._recent_message_limit = recent_message_limit

    def update(
        self,
        *,
        previous_messages: list[ContextMessage],
        current_input: ContextMessage,
        final_text: str,
    ) -> RecentWindowResult:
        """追加最新轮次消息，并拆分出保留消息与被挤出消息。"""
        combined_messages = [
            *previous_messages,
            current_input,
            ContextMessage(role="assistant", content=final_text),
        ]
        if len(combined_messages) <= self._recent_message_limit:
            return RecentWindowResult(
                recent_messages=combined_messages,
                evicted_messages=[],
            )

        evicted_count = len(combined_messages) - self._recent_message_limit
        return RecentWindowResult(
            recent_messages=combined_messages[evicted_count:],
            evicted_messages=combined_messages[:evicted_count],
        )


class SummaryBufferManager:
    """累计被挤出的最近消息，等待后续摘要压缩。"""

    def __init__(
        self,
        *,
        flush_message_count: int,
        flush_char_count: int,
    ) -> None:
        """保存决定摘要缓冲区何时刷新的阈值。"""
        self._flush_message_count = flush_message_count
        self._flush_char_count = flush_char_count

    def update(
        self,
        *,
        previous_buffer: list[ContextMessage],
        evicted_messages: list[ContextMessage],
    ) -> SummaryBufferDecision:
        """将新挤出消息合并到摘要缓冲区，并判断是否需要刷新。"""
        next_buffer = [*previous_buffer, *evicted_messages]
        if not next_buffer:
            return SummaryBufferDecision(
                next_buffer=[],
                should_flush=False,
                flush_messages=[],
                reason="buffer_empty",
            )

        buffered_chars = sum(len(message.content) for message in next_buffer)
        if len(next_buffer) >= self._flush_message_count:
            return SummaryBufferDecision(
                next_buffer=next_buffer,
                should_flush=True,
                flush_messages=list(next_buffer),
                reason="message_threshold",
            )
        if buffered_chars >= self._flush_char_count:
            return SummaryBufferDecision(
                next_buffer=next_buffer,
                should_flush=True,
                flush_messages=list(next_buffer),
                reason="char_threshold",
            )
        return SummaryBufferDecision(
            next_buffer=next_buffer,
            should_flush=False,
            flush_messages=[],
            reason="below_threshold",
        )

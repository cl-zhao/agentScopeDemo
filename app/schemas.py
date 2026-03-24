"""HTTP API 的数据模型定义。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResponseMode(str, Enum):
    """单次执行支持的响应载荷样式。"""

    TEXT = "text"
    TASK_RESULT = "task_result"


class SessionCreateResponse(BaseModel):
    """保留用于兼容的旧版会话创建响应。"""

    session_id: str = Field(description="Server-generated session identifier.")


class ChatStreamRequest(BaseModel):
    """为迁移兼容保留的旧版流式聊天请求模型。"""

    message: str = Field(min_length=1, description="User message content.")
    response_mode: ResponseMode = Field(
        default=ResponseMode.TEXT,
        description="Legacy response mode toggle.",
    )
    access_param: str = Field(
        min_length=1,
        description="Caller identity token used for request attribution.",
    )


class RawModelStreamRequest(BaseModel):
    """用于原始上游模型流调试的请求体。"""

    message: str = Field(
        min_length=1,
        description="Message sent directly to the upstream chat model.",
    )


class SessionStatusResponse(BaseModel):
    """为兼容旧接口保留的旧版会话状态响应。"""

    session_id: str = Field(description="Session identifier.")
    status: str = Field(description="Session status.")
    updated_at: datetime = Field(description="Last update timestamp.")
    last_result: dict[str, Any] | None = Field(
        default=None,
        description="Last response payload captured for the session.",
    )


class InterruptResponse(BaseModel):
    """旧版会话中断响应。"""

    session_id: str = Field(description="Session identifier.")
    interrupted: bool = Field(description="Whether an interrupt signal was issued.")
    status: str = Field(description="Session status after the interrupt request.")


class TaskResultSchema(BaseModel):
    """当 `response_mode=task_result` 时返回的结构化任务结果。"""

    summary: str = Field(description="Task result summary.")
    actions: list[str] = Field(
        default_factory=list,
        description="Actions performed or recommended.",
    )
    risks: list[str] = Field(
        default_factory=list,
        description="Risks or caveats found during the task.",
    )
    next_steps: list[str] = Field(
        default_factory=list,
        description="Suggested next actions.",
    )


class ContextMessage(BaseModel):
    """调用方传入的一条规范化对话消息。"""

    role: Literal["user", "assistant", "system"] = Field(
        description="Semantic role for the message.",
    )
    content: str = Field(min_length=1, description="Plain-text message content.")


class ContextMemoryMeta(BaseModel):
    """由引擎维护的增量上下文元数据。"""

    turn_count: int = Field(default=0, description="Number of turns accumulated in this package.")
    summary_revision: int = Field(default=0, description="Number of summary refreshes applied.")
    last_summary_turn: int = Field(
        default=0,
        description="Turn number when summary was last refreshed.",
    )
    summary_buffer: list[ContextMessage] = Field(
        default_factory=list,
        description="Evicted recent messages awaiting future summary compression.",
    )


class ContextArtifact(BaseModel):
    """从早期执行中保留的原始或半结构化 artifact。"""

    id: str = Field(min_length=1, description="Artifact identifier.")
    type: str = Field(min_length=1, description="Artifact type label.")
    tool_name: str | None = Field(
        default=None,
        description="Tool name associated with the artifact, if applicable.",
    )
    content: dict[str, Any] | list[Any] | str = Field(
        description="Artifact payload preserved for later reuse or trimming.",
    )
    importance: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Relative priority used by the context compiler.",
    )
    created_at: datetime | None = Field(
        default=None,
        description="Artifact creation timestamp, if available.",
    )


class ContextPackage(BaseModel):
    """供无状态执行使用、由调用方维护的上下文包。"""

    version: str = Field(default="1.0", description="Context package version.")
    summary: str = Field(
        default="",
        description="Compressed summary of older conversation state.",
    )
    state: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured state such as facts, slots, and tool state.",
    )
    recent_messages: list[ContextMessage] = Field(
        default_factory=list,
        description="Most recent full-fidelity conversation turns.",
    )
    artifacts: list[ContextArtifact] = Field(
        default_factory=list,
        description="Artifacts retained from prior tool invocations or results.",
    )
    memory_meta: ContextMemoryMeta = Field(
        default_factory=ContextMemoryMeta,
        description="Engine-managed metadata used for incremental memory updates.",
    )


class ExecutionStreamRequest(BaseModel):
    """无状态执行的主请求模型。"""

    session_id: str = Field(
        min_length=1,
        description="Caller-supplied correlation identifier.",
    )
    access_param: str = Field(
        min_length=1,
        description="Caller identity token used for attribution and authorization.",
    )
    response_mode: ResponseMode = Field(
        default=ResponseMode.TEXT,
        description="Desired final response payload mode.",
    )
    return_context_package: bool = Field(
        default=False,
        description="Whether the engine should return an updated context package.",
    )
    context_package: ContextPackage = Field(
        default_factory=ContextPackage,
        description="Caller-managed context envelope.",
    )
    current_input: ContextMessage = Field(
        description="The new user turn to execute against the compiled context.",
    )


class ExecutionResponse(BaseModel):
    """非流式接口返回的最终执行响应。"""

    execution_id: str = Field(description="Execution identifier.")
    session_id: str = Field(description="Caller session identifier.")
    status: str = Field(description="Execution status.")
    text: str = Field(description="Assistant response text.")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary execution metadata.",
    )
    response_mode: ResponseMode = Field(description="Final response mode used.")
    next_context_package: ContextPackage | None = Field(
        default=None,
        description="Updated context package when requested by the caller.",
    )


class ExecutionStatusResponse(BaseModel):
    """执行状态查询响应。"""

    execution_id: str = Field(description="Execution identifier.")
    session_id: str = Field(description="Caller session identifier.")
    status: str = Field(description="Execution status.")
    started_at: datetime | None = Field(
        default=None,
        description="Execution start timestamp.",
    )
    updated_at: datetime = Field(description="Last update timestamp.")
    finished_at: datetime | None = Field(
        default=None,
        description="Execution finish timestamp.",
    )
    last_error: str | None = Field(
        default=None,
        description="Latest error message, if execution failed.",
    )


class ExecutionInterruptResponse(BaseModel):
    """执行中断响应。"""

    execution_id: str = Field(description="Execution identifier.")
    interrupted: bool = Field(description="Whether an interrupt signal was issued.")
    status: str = Field(description="Execution status after the interrupt request.")

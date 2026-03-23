"""HTTP API schema models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResponseMode(str, Enum):
    """Supported response payload styles for one execution."""

    TEXT = "text"
    TASK_RESULT = "task_result"


class SessionCreateResponse(BaseModel):
    """Legacy response for session creation."""

    session_id: str = Field(description="Server-generated session identifier.")


class ChatStreamRequest(BaseModel):
    """Legacy stream-chat request model kept for migration compatibility."""

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
    """Request body for raw upstream model streaming debug."""

    message: str = Field(
        min_length=1,
        description="Message sent directly to the upstream chat model.",
    )


class SessionStatusResponse(BaseModel):
    """Legacy session status response kept for compatibility endpoints."""

    session_id: str = Field(description="Session identifier.")
    status: str = Field(description="Session status.")
    updated_at: datetime = Field(description="Last update timestamp.")
    last_result: dict[str, Any] | None = Field(
        default=None,
        description="Last response payload captured for the session.",
    )


class InterruptResponse(BaseModel):
    """Legacy session interrupt response."""

    session_id: str = Field(description="Session identifier.")
    interrupted: bool = Field(description="Whether an interrupt signal was issued.")
    status: str = Field(description="Session status after the interrupt request.")


class TaskResultSchema(BaseModel):
    """Structured task-result response requested via ``response_mode=task_result``."""

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
    """One normalized conversational message entry supplied by the caller."""

    role: Literal["user", "assistant", "system"] = Field(
        description="Semantic role for the message.",
    )
    content: str = Field(min_length=1, description="Plain-text message content.")


class ContextArtifact(BaseModel):
    """Raw or semi-structured artifact retained from earlier executions."""

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
    """Caller-managed context envelope for stateless execution."""

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


class ExecutionStreamRequest(BaseModel):
    """Primary stateless execution request model."""

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
    """Final execution response payload for non-streaming endpoints."""

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
    """Execution status query response."""

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
    """Execution interruption response."""

    execution_id: str = Field(description="Execution identifier.")
    interrupted: bool = Field(description="Whether an interrupt signal was issued.")
    status: str = Field(description="Execution status after the interrupt request.")

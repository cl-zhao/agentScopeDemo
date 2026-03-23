"""Execution-layer error types."""

from __future__ import annotations


class ExecutionNotFoundError(KeyError):
    """Raised when an execution cannot be found."""


class SessionAlreadyRunningError(RuntimeError):
    """Raised when a session already has an active execution."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session already has an active execution: {session_id}")
        self.session_id = session_id

"""In-process execution registry."""

from __future__ import annotations

from app.execution.models import RunningExecutionHandle


class ExecutionRegistry:
    """Tracks active execution handles for the current process."""

    def __init__(self) -> None:
        self._by_execution: dict[str, RunningExecutionHandle] = {}
        self._by_session: dict[str, str] = {}

    def register(self, handle: RunningExecutionHandle) -> None:
        self._by_execution[handle.execution_id] = handle
        self._by_session[handle.session_id] = handle.execution_id

    def get(self, execution_id: str) -> RunningExecutionHandle | None:
        return self._by_execution.get(execution_id)

    def find_by_session(self, session_id: str) -> RunningExecutionHandle | None:
        execution_id = self._by_session.get(session_id)
        if execution_id is None:
            return None
        return self._by_execution.get(execution_id)

    def pop(self, execution_id: str) -> RunningExecutionHandle | None:
        handle = self._by_execution.pop(execution_id, None)
        if handle is None:
            return None
        self._by_session.pop(handle.session_id, None)
        return handle

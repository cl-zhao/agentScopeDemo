"""进程内执行注册表。"""

from __future__ import annotations

from app.execution.models import RunningExecutionHandle


class ExecutionRegistry:
    """跟踪当前进程中的活跃执行句柄。"""

    def __init__(self) -> None:
        """初始化空的执行与会话索引表。"""
        self._by_execution: dict[str, RunningExecutionHandle] = {}
        self._by_session: dict[str, str] = {}

    def register(self, handle: RunningExecutionHandle) -> None:
        """按执行 ID 和会话 ID 双索引注册运行中执行句柄。"""
        self._by_execution[handle.execution_id] = handle
        self._by_session[handle.session_id] = handle.execution_id

    def get(self, execution_id: str) -> RunningExecutionHandle | None:
        """按执行 ID 返回运行中执行句柄。"""
        return self._by_execution.get(execution_id)

    def find_by_session(self, session_id: str) -> RunningExecutionHandle | None:
        """返回当前映射到指定会话 ID 的运行中执行句柄。"""
        execution_id = self._by_session.get(session_id)
        if execution_id is None:
            return None
        return self._by_execution.get(execution_id)

    def pop(self, execution_id: str) -> RunningExecutionHandle | None:
        """从两个索引中移除并返回指定执行句柄。"""
        handle = self._by_execution.pop(execution_id, None)
        if handle is None:
            return None
        self._by_session.pop(handle.session_id, None)
        return handle

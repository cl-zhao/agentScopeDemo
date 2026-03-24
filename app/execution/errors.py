"""执行层错误类型。"""

from __future__ import annotations


class ExecutionNotFoundError(KeyError):
    """当找不到指定执行时抛出。"""


class SessionAlreadyRunningError(RuntimeError):
    """当会话已经存在活跃执行时抛出。"""

    def __init__(self, session_id: str) -> None:
        """在异常对象中记录发生冲突的会话 ID。"""
        super().__init__(f"Session already has an active execution: {session_id}")
        self.session_id = session_id

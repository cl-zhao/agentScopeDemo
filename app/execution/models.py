"""执行层数据模型。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RunningExecutionHandle:
    """单个运行中执行在进程内的句柄。"""

    execution_id: str
    session_id: str
    agent: Any
    task: asyncio.Task | None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ExecutionRecord:
    """存储在 Redis 中的单次执行控制面记录。"""

    execution_id: str
    session_id: str
    status: str
    owner_instance: str
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    last_error: str | None = None

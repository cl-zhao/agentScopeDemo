"""Execution-layer data models."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class RunningExecutionHandle:
    """In-process handle for one running execution."""

    execution_id: str
    session_id: str
    agent: Any
    task: asyncio.Task | None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

from __future__ import annotations

import asyncio

import pytest

from app.execution.registry import ExecutionRegistry
from app.execution.models import RunningExecutionHandle


@pytest.mark.asyncio
async def test_registry_registers_and_releases_execution() -> None:
    registry = ExecutionRegistry()
    task = asyncio.create_task(asyncio.sleep(0))
    handle = RunningExecutionHandle(
        execution_id="exec-1",
        session_id="session-1",
        agent=object(),
        task=task,
    )

    registry.register(handle)
    assert registry.get("exec-1") is handle

    removed = registry.pop("exec-1")
    assert removed is handle
    assert registry.get("exec-1") is None

    await task


def test_registry_maps_session_to_execution() -> None:
    registry = ExecutionRegistry()
    handle = RunningExecutionHandle(
        execution_id="exec-1",
        session_id="session-1",
        agent=object(),
        task=None,
    )

    registry.register(handle)

    assert registry.find_by_session("session-1") is handle

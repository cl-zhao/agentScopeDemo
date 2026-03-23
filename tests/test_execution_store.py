from __future__ import annotations

import pytest

from app.execution.store import ExecutionStore


class FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    async def set(self, key: str, value: object, ex: int | None = None, nx: bool = False):
        _ = ex
        if nx and key in self._data:
            return False
        self._data[key] = value
        return True

    async def get(self, key: str):
        return self._data.get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                deleted += 1
        return deleted


@pytest.mark.asyncio
async def test_store_claims_session_once() -> None:
    store = ExecutionStore(redis_client=FakeRedis(), key_prefix="ai-engine")

    claimed = await store.claim_session("session-1", "exec-1", ttl_seconds=60)
    duplicate = await store.claim_session("session-1", "exec-2", ttl_seconds=60)

    assert claimed is True
    assert duplicate is False


@pytest.mark.asyncio
async def test_store_sets_interrupt_flag() -> None:
    store = ExecutionStore(redis_client=FakeRedis(), key_prefix="ai-engine")

    await store.set_interrupt_requested("exec-1")

    assert await store.is_interrupt_requested("exec-1") is True

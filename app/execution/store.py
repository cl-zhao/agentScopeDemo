"""Redis-backed execution control store."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.execution.models import ExecutionRecord


class ExecutionStore:
    """Stores execution metadata and interrupt flags in Redis."""

    def __init__(self, *, redis_client: Any, key_prefix: str) -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix

    def _session_key(self, session_id: str) -> str:
        return f"{self._key_prefix}:session:active:{session_id}"

    def _execution_key(self, execution_id: str) -> str:
        return f"{self._key_prefix}:execution:{execution_id}"

    def _interrupt_key(self, execution_id: str) -> str:
        return f"{self._key_prefix}:execution:interrupt:{execution_id}"

    async def claim_session(
        self,
        session_id: str,
        execution_id: str,
        ttl_seconds: int,
    ) -> bool:
        claimed = await self._redis.set(
            self._session_key(session_id),
            execution_id,
            ex=ttl_seconds,
            nx=True,
        )
        return bool(claimed)

    async def release_session(self, session_id: str, execution_id: str) -> None:
        current = await self._redis.get(self._session_key(session_id))
        if self._decode_scalar(current) == execution_id:
            await self._redis.delete(self._session_key(session_id))

    async def save_execution_record(
        self,
        record: ExecutionRecord,
        ttl_seconds: int,
    ) -> None:
        payload = {
            "execution_id": record.execution_id,
            "session_id": record.session_id,
            "status": record.status,
            "owner_instance": record.owner_instance,
            "started_at": record.started_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "finished_at": record.finished_at.isoformat() if record.finished_at else None,
            "last_error": record.last_error,
        }
        await self._redis.set(
            self._execution_key(record.execution_id),
            json.dumps(payload, ensure_ascii=False),
            ex=ttl_seconds,
        )

    async def get_execution_record(self, execution_id: str) -> ExecutionRecord | None:
        raw = await self._redis.get(self._execution_key(execution_id))
        if raw is None:
            return None
        payload = json.loads(self._decode_scalar(raw))
        return ExecutionRecord(
            execution_id=payload["execution_id"],
            session_id=payload["session_id"],
            status=payload["status"],
            owner_instance=payload["owner_instance"],
            started_at=datetime.fromisoformat(payload["started_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            finished_at=(
                datetime.fromisoformat(payload["finished_at"])
                if payload["finished_at"]
                else None
            ),
            last_error=payload["last_error"],
        )

    async def update_execution_status(
        self,
        execution_id: str,
        status: str,
        *,
        ttl_seconds: int,
        last_error: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        record = await self.get_execution_record(execution_id)
        if record is None:
            return
        record.status = status
        record.updated_at = datetime.now(record.updated_at.tzinfo)
        if finished_at is not None:
            record.finished_at = finished_at
        if last_error is not None:
            record.last_error = last_error
        await self.save_execution_record(record, ttl_seconds=ttl_seconds)

    async def set_interrupt_requested(
        self,
        execution_id: str,
        ttl_seconds: int = 3600,
    ) -> None:
        await self._redis.set(self._interrupt_key(execution_id), "1", ex=ttl_seconds)

    async def is_interrupt_requested(self, execution_id: str) -> bool:
        value = await self._redis.get(self._interrupt_key(execution_id))
        return self._decode_scalar(value) == "1"

    @staticmethod
    def _decode_scalar(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

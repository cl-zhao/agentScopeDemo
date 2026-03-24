"""基于 Redis 的执行控制存储。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.execution.models import ExecutionRecord


class ExecutionStore:
    """在 Redis 中存储执行元数据和中断标记。"""

    def __init__(self, *, redis_client: Any, key_prefix: str) -> None:
        """保存 Redis 客户端以及执行记录的命名空间前缀。"""
        self._redis = redis_client
        self._key_prefix = key_prefix

    def _session_key(self, session_id: str) -> str:
        """构造会话活跃执行占用记录对应的 Redis 键。"""
        return f"{self._key_prefix}:session:active:{session_id}"

    def _execution_key(self, execution_id: str) -> str:
        """构造执行记录持久化对应的 Redis 键。"""
        return f"{self._key_prefix}:execution:{execution_id}"

    def _interrupt_key(self, execution_id: str) -> str:
        """构造执行中断标记对应的 Redis 键。"""
        return f"{self._key_prefix}:execution:interrupt:{execution_id}"

    async def claim_session(
        self,
        session_id: str,
        execution_id: str,
        ttl_seconds: int,
    ) -> bool:
        """使用 Redis 的 NX 语义尝试为一次执行占用会话。"""
        claimed = await self._redis.set(
            self._session_key(session_id),
            execution_id,
            ex=ttl_seconds,
            nx=True,
        )
        return bool(claimed)

    async def release_session(self, session_id: str, execution_id: str) -> None:
        """仅当会话仍属于指定执行时才释放占用。"""
        current = await self._redis.get(self._session_key(session_id))
        if self._decode_scalar(current) == execution_id:
            await self._redis.delete(self._session_key(session_id))

    async def get_active_execution_id(self, session_id: str) -> str | None:
        """返回当前被指定会话占用的活跃执行 ID。"""
        value = await self._redis.get(self._session_key(session_id))
        return self._decode_scalar(value)

    async def save_execution_record(
        self,
        record: ExecutionRecord,
        ttl_seconds: int,
    ) -> None:
        """将一份执行记录快照持久化到 Redis。"""
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
        """从 Redis 读取并反序列化一份执行记录。"""
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
        """更新一份已持久化执行记录中的可变状态字段。"""
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
        """为指定执行持久化中断标记。"""
        await self._redis.set(self._interrupt_key(execution_id), "1", ex=ttl_seconds)

    async def is_interrupt_requested(self, execution_id: str) -> bool:
        """判断指定执行当前是否已设置中断标记。"""
        value = await self._redis.get(self._interrupt_key(execution_id))
        return self._decode_scalar(value) == "1"

    async def clear_interrupt_requested(self, execution_id: str) -> None:
        """清除指定执行的持久化中断标记。"""
        await self._redis.delete(self._interrupt_key(execution_id))

    @staticmethod
    def _decode_scalar(value: Any) -> str | None:
        """将 Redis 标量返回值解码成便于后续处理的文本。"""
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

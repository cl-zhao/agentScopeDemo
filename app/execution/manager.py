"""Execution orchestration for the stateless AI engine."""

from __future__ import annotations

import asyncio
import socket
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import uuid4

from agentscope.message import Msg

from app.agent.litellm_context import (
    build_litellm_request_context,
    reset_current_litellm_request_context,
    set_current_litellm_request_context,
)
from app.config import AppConfig
from app.execution.context_compiler import CompiledContext, ContextCompiler
from app.execution.context_package import ContextPackageUpdater, build_tool_artifact
from app.execution.errors import ExecutionNotFoundError, SessionAlreadyRunningError
from app.execution.models import ExecutionRecord, RunningExecutionHandle
from app.execution.registry import ExecutionRegistry
from app.execution.store import ExecutionStore
from app.execution.stream_adapter import StreamEventAdapter
from app.schemas import (
    ContextArtifact,
    ExecutionInterruptResponse,
    ExecutionResponse,
    ExecutionStatusResponse,
    ExecutionStreamRequest,
    ResponseMode,
    TaskResultSchema,
)
from app.security.security_manager import get_decrypted_principal


class ExecutionManager:
    """Coordinates one request-scoped ReAct agent execution."""

    def __init__(
        self,
        *,
        config: AppConfig,
        factory: Any,
        store: ExecutionStore,
        registry: ExecutionRegistry,
        compiler: ContextCompiler,
        context_package_updater: ContextPackageUpdater,
        stream_adapter: StreamEventAdapter | None = None,
        instance_name: str | None = None,
    ) -> None:
        self._config = config
        self._factory = factory
        self._store = store
        self._registry = registry
        self._compiler = compiler
        self._context_package_updater = context_package_updater
        self._stream_adapter = stream_adapter or StreamEventAdapter()
        self._instance_name = instance_name or socket.gethostname()

    async def stream_execution(
        self,
        request: ExecutionStreamRequest,
    ) -> AsyncGenerator[dict[str, Any], None]:
        execution_id = str(uuid4())
        now = datetime.now(timezone.utc)
        claimed = await self._store.claim_session(
            request.session_id,
            execution_id,
            ttl_seconds=self._config.session_active_ttl_seconds,
        )
        if not claimed:
            raise SessionAlreadyRunningError(request.session_id)

        record = ExecutionRecord(
            execution_id=execution_id,
            session_id=request.session_id,
            status="running",
            owner_instance=self._instance_name,
            started_at=now,
            updated_at=now,
        )
        await self._store.save_execution_record(
            record,
            ttl_seconds=self._config.execution_record_ttl_seconds,
        )

        principal = get_decrypted_principal(request.access_param)
        compiled_context = self._compiler.compile(
            context_package=request.context_package,
            current_input=request.current_input,
        )
        agent = await self._factory.create_agent()
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        agent.set_msg_queue_enabled(True, queue=queue)

        request_context = build_litellm_request_context(
            principal,
            session_id=request.session_id,
            execution_id=execution_id,
            app_request_id=str(uuid4()),
        )
        context_token = set_current_litellm_request_context(request_context)

        user_msg = Msg(
            name=request.current_input.role,
            role=request.current_input.role,
            content=compiled_context.prompt_text,
        )
        structured_model = (
            TaskResultSchema
            if request.response_mode == ResponseMode.TASK_RESULT
            else None
        )

        running_task = asyncio.create_task(
            self._run_agent_task(agent=agent, user_msg=user_msg, structured_model=structured_model)
        )
        self._registry.register(
            RunningExecutionHandle(
                execution_id=execution_id,
                session_id=request.session_id,
                agent=agent,
                task=running_task,
            )
        )

        collected_artifacts: list[ContextArtifact] = []
        final_payload: dict[str, Any] | None = None

        try:
            yield self._build_event(
                event_type="execution_started",
                execution_id=execution_id,
                session_id=request.session_id,
                payload={"status": "running"},
            )

            async for event in self._drain_message_queue(
                execution_id=execution_id,
                session_id=request.session_id,
                queue=queue,
                task=running_task,
                collected_artifacts=collected_artifacts,
            ):
                yield event

            result_msg = await running_task
            metadata = result_msg.metadata if isinstance(result_msg.metadata, dict) else {}
            is_interrupted = bool(metadata.get("_is_interrupted", False))
            status = "interrupted" if is_interrupted else "completed"

            if is_interrupted:
                await self._store.update_execution_status(
                    execution_id,
                    status,
                    ttl_seconds=self._config.execution_record_ttl_seconds,
                    finished_at=datetime.now(timezone.utc),
                )
                yield self._build_event(
                    event_type="interrupted",
                    execution_id=execution_id,
                    session_id=request.session_id,
                    payload={
                        "message": result_msg.get_text_content() or "",
                        "metadata": metadata,
                    },
                )
            else:
                await self._store.update_execution_status(
                    execution_id,
                    status,
                    ttl_seconds=self._config.execution_record_ttl_seconds,
                    finished_at=datetime.now(timezone.utc),
                )

            final_payload = {
                "text": result_msg.get_text_content() or "",
                "metadata": metadata,
                "response_mode": request.response_mode.value,
            }
            if request.return_context_package and not is_interrupted:
                final_payload["next_context_package"] = (
                    self._context_package_updater.build_next_package(
                        previous=request.context_package,
                        current_input=request.current_input,
                        final_text=final_payload["text"],
                        artifacts=collected_artifacts,
                    ).model_dump(mode="json")
                )
            yield self._build_event(
                event_type="final",
                execution_id=execution_id,
                session_id=request.session_id,
                payload=final_payload,
            )
        except Exception as exc:
            await self._store.update_execution_status(
                execution_id,
                "failed",
                ttl_seconds=self._config.execution_record_ttl_seconds,
                last_error=str(exc),
                finished_at=datetime.now(timezone.utc),
            )
            yield self._build_event(
                event_type="error",
                execution_id=execution_id,
                session_id=request.session_id,
                payload={"message": str(exc)},
            )
            return
        finally:
            reset_current_litellm_request_context(context_token)
            self._registry.pop(execution_id)
            agent.set_msg_queue_enabled(False)
            await self._store.release_session(request.session_id, execution_id)
            await self._store.clear_interrupt_requested(execution_id)

    async def run_execution(self, request: ExecutionStreamRequest) -> ExecutionResponse:
        final_event: dict[str, Any] | None = None
        async for event in self.stream_execution(request):
            if event["event_type"] == "final":
                final_event = event
        if final_event is None:
            raise RuntimeError("Execution did not produce a final event")

        payload = final_event["payload"]
        return ExecutionResponse(
            execution_id=final_event["execution_id"],
            session_id=final_event["session_id"],
            status="completed",
            text=payload["text"],
            metadata=payload.get("metadata", {}),
            response_mode=ResponseMode(payload["response_mode"]),
            next_context_package=payload.get("next_context_package"),
        )

    async def get_execution_status(self, execution_id: str) -> ExecutionStatusResponse:
        record = await self._store.get_execution_record(execution_id)
        if record is None:
            raise ExecutionNotFoundError(execution_id)
        return ExecutionStatusResponse(
            execution_id=record.execution_id,
            session_id=record.session_id,
            status=record.status,
            started_at=record.started_at,
            updated_at=record.updated_at,
            finished_at=record.finished_at,
            last_error=record.last_error,
        )

    async def interrupt_execution(
        self,
        execution_id: str,
    ) -> ExecutionInterruptResponse:
        record = await self._store.get_execution_record(execution_id)
        if record is None:
            raise ExecutionNotFoundError(execution_id)

        await self._store.set_interrupt_requested(
            execution_id,
            ttl_seconds=self._config.execution_record_ttl_seconds,
        )
        handle = self._registry.get(execution_id)
        if handle is not None and handle.task is not None and not handle.task.done():
            # Local interrupt is best-effort immediate. The stream loop still checks
            # the Redis flag so remote-worker interruption can share the same path.
            await handle.agent.interrupt()
            return ExecutionInterruptResponse(
                execution_id=execution_id,
                interrupted=True,
                status="interrupted",
            )

        return ExecutionInterruptResponse(
            execution_id=execution_id,
            interrupted=False,
            status=record.status,
        )

    async def interrupt_session(self, session_id: str) -> ExecutionInterruptResponse:
        execution_id = await self._store.get_active_execution_id(session_id)
        if execution_id is None:
            raise ExecutionNotFoundError(session_id)
        return await self.interrupt_execution(execution_id)

    async def _run_agent_task(
        self,
        *,
        agent: Any,
        user_msg: Msg,
        structured_model: type[TaskResultSchema] | None,
    ) -> Msg:
        if structured_model is None:
            return await agent(user_msg)
        return await agent(user_msg, structured_model=structured_model)

    async def _drain_message_queue(
        self,
        *,
        execution_id: str,
        session_id: str,
        queue: asyncio.Queue,
        task: asyncio.Task,
        collected_artifacts: list[ContextArtifact],
    ) -> AsyncGenerator[dict[str, Any], None]:
        while True:
            if task.done() and queue.empty():
                break

            if await self._store.is_interrupt_requested(execution_id):
                handle = self._registry.get(execution_id)
                if handle is not None and handle.task is not None and not handle.task.done():
                    await handle.agent.interrupt()

            try:
                queued_msg, is_last, _speech = await asyncio.wait_for(queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                continue

            extracted_events = self._stream_adapter.extract_events(queued_msg, is_last=is_last)
            for event_type, payload in extracted_events:
                if event_type == "tool_call" and payload.get("status") == "completed":
                    collected_artifacts.append(build_tool_artifact(payload))
                yield self._build_event(
                    event_type=event_type,
                    execution_id=execution_id,
                    session_id=session_id,
                    payload=payload,
                )

    def _build_event(
        self,
        *,
        event_type: str,
        execution_id: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "execution_id": execution_id,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "payload": payload,
        }

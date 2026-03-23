"""HTTP routes for the stateless execution engine."""

from __future__ import annotations

import json
import socket
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from openai import AsyncClient
from redis.asyncio import Redis

from app.agent.factory import AgentFactory
from app.config import AppConfig
from app.execution.context_compiler import ContextCompiler
from app.execution.context_package import ContextPackageUpdater
from app.execution.errors import ExecutionNotFoundError, SessionAlreadyRunningError
from app.execution.manager import ExecutionManager
from app.execution.registry import ExecutionRegistry
from app.execution.store import ExecutionStore
from app.schemas import (
    ExecutionInterruptResponse,
    ExecutionResponse,
    ExecutionStatusResponse,
    ExecutionStreamRequest,
    RawModelStreamRequest,
)
from app.tools import PythonSafetyConfig, SafePythonExecutor

router = APIRouter(prefix="/v1", tags=["agent"])


def _to_sse_data(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _build_execution_manager(config: AppConfig) -> ExecutionManager:
    safety_config = PythonSafetyConfig(
        default_timeout=config.python_tool_timeout,
        max_code_length=config.python_tool_max_code_length,
        max_output_length=config.python_tool_max_output_length,
    )
    python_executor = SafePythonExecutor(safety_config)
    redis_client = Redis.from_url(config.redis_url)

    return ExecutionManager(
        config=config,
        factory=AgentFactory(config=config, python_executor=python_executor),
        store=ExecutionStore(
            redis_client=redis_client,
            key_prefix=config.redis_key_prefix,
        ),
        registry=ExecutionRegistry(),
        compiler=ContextCompiler(
            recent_message_limit=config.context_recent_message_limit,
            artifact_char_budget=config.context_artifact_char_budget,
        ),
        context_package_updater=ContextPackageUpdater(
            recent_message_limit=config.context_recent_message_limit,
        ),
        instance_name=socket.gethostname(),
    )


def get_execution_manager(request: Request) -> ExecutionManager:
    manager = getattr(request.app.state, "execution_manager", None)
    if manager is None:
        manager = _build_execution_manager(AppConfig.from_env())
        request.app.state.execution_manager = manager
    return manager


@router.post("/executions/stream")
async def stream_execution(
    request_body: ExecutionStreamRequest,
    manager: ExecutionManager = Depends(get_execution_manager),
) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event in manager.stream_execution(request_body):
                yield _to_sse_data(event)
        except SessionAlreadyRunningError as exc:
            yield _to_sse_data(
                {
                    "event_type": "error",
                    "execution_id": None,
                    "session_id": request_body.session_id,
                    "timestamp": None,
                    "payload": {"message": str(exc)},
                }
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/executions", response_model=ExecutionResponse)
async def run_execution(
    request_body: ExecutionStreamRequest,
    manager: ExecutionManager = Depends(get_execution_manager),
) -> ExecutionResponse:
    try:
        return await manager.run_execution(request_body)
    except SessionAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/executions/{execution_id}",
    response_model=ExecutionStatusResponse,
)
async def get_execution_status(
    execution_id: str,
    manager: ExecutionManager = Depends(get_execution_manager),
) -> ExecutionStatusResponse:
    try:
        return await manager.get_execution_status(execution_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/executions/{execution_id}/interrupt",
    response_model=ExecutionInterruptResponse,
)
async def interrupt_execution(
    execution_id: str,
    manager: ExecutionManager = Depends(get_execution_manager),
) -> ExecutionInterruptResponse:
    try:
        return await manager.interrupt_execution(execution_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/interrupt",
    response_model=ExecutionInterruptResponse,
)
async def interrupt_session(
    session_id: str,
    manager: ExecutionManager = Depends(get_execution_manager),
) -> ExecutionInterruptResponse:
    try:
        return await manager.interrupt_session(session_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/debug/raw-model/stream")
async def debug_raw_model_stream(
    request_body: RawModelStreamRequest,
) -> StreamingResponse:
    config = AppConfig.from_env()

    async def event_generator() -> AsyncGenerator[str, None]:
        client = AsyncClient(
            api_key=config.ark_api_key,
            base_url=config.ark_base_url,
        )
        try:
            response = await client.chat.completions.create(
                model=config.ark_model,
                messages=[{"role": "user", "content": request_body.message}],
                stream=True,
                temperature=config.model_temperature,
            )
            async for chunk in response:
                if hasattr(chunk, "model_dump"):
                    raw_payload = chunk.model_dump(mode="json")
                else:
                    raw_payload = {"raw": str(chunk)}
                yield _to_sse_data(
                    {
                        "event_type": "raw_chunk",
                        "timestamp": None,
                        "payload": raw_payload,
                    }
                )
            yield _to_sse_data(
                {
                    "event_type": "raw_done",
                    "timestamp": None,
                    "payload": {},
                }
            )
        except Exception as exc:  # noqa: BLE001
            yield _to_sse_data(
                {
                    "event_type": "raw_error",
                    "timestamp": None,
                    "payload": {"message": str(exc)},
                }
            )
        finally:
            await client.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

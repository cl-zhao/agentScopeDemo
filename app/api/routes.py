"""无状态执行引擎的 HTTP 路由。"""

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
    """将单个事件字典序列化为 SSE 传输格式。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _build_execution_manager(config: AppConfig) -> ExecutionManager:
    """为当前进程构建默认的执行管理器。"""
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
            summary_buffer_flush_messages=config.context_summary_buffer_flush_messages,
            summary_buffer_flush_chars=config.context_summary_buffer_flush_chars,
            state_pending_question_limit=config.context_state_pending_question_limit,
            summary_max_items_per_section=config.context_summary_max_items_per_section,
            summary_message_snippet_length=config.context_summary_message_snippet_length,
            summary_max_length=config.context_summary_max_length,
        ),
        instance_name=socket.gethostname(),
    )


def get_execution_manager(request: Request) -> ExecutionManager:
    """返回缓存的执行管理器，首次访问时再延迟创建。"""
    manager = getattr(request.app.state, "execution_manager", None)
    if manager is None:
        config = getattr(request.app.state, "app_config", None)
        if config is None:
            config = AppConfig.from_env()
            request.app.state.app_config = config
        manager = _build_execution_manager(config)
        request.app.state.execution_manager = manager
    return manager


def _resolve_request_config(
    request: Request,
    manager: ExecutionManager,
) -> AppConfig:
    """解析本次请求应使用的应用配置。"""
    config = getattr(request.app.state, "app_config", None)
    if config is not None:
        return config
    manager_config = getattr(manager, "_config", None)
    if manager_config is not None:
        request.app.state.app_config = manager_config
        return manager_config
    config = AppConfig.from_env()
    request.app.state.app_config = config
    return config


def _validate_allowed_openai_params(
    request_body: ExecutionStreamRequest,
    config: AppConfig,
) -> None:
    """校验请求级透传参数未覆盖保留字段。"""
    if not request_body.allowed_openai_params:
        return

    reserved_keys = set(config.model_request_config.non_overridable_request_params)
    blocked_keys = [
        key for key in request_body.allowed_openai_params if key in reserved_keys
    ]
    if blocked_keys:
        joined = ", ".join(blocked_keys)
        raise HTTPException(
            status_code=400,
            detail=(
                "allowed_openai_params contains non-overridable keys: "
                f"{joined}"
            ),
        )


@router.post("/executions/stream")
async def stream_execution(
    request: Request,
    request_body: ExecutionStreamRequest,
    manager: ExecutionManager = Depends(get_execution_manager),
) -> StreamingResponse:
    """以 SSE 响应形式暴露主执行流程。"""
    _validate_allowed_openai_params(
        request_body=request_body,
        config=_resolve_request_config(request, manager),
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        """持续产出 SSE 事件帧，并向调用方返回会话冲突错误。"""
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
    request: Request,
    request_body: ExecutionStreamRequest,
    manager: ExecutionManager = Depends(get_execution_manager),
) -> ExecutionResponse:
    """执行一次完整请求并返回最终结果。"""
    _validate_allowed_openai_params(
        request_body=request_body,
        config=_resolve_request_config(request, manager),
    )
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
    """返回指定执行 ID 的持久化状态。"""
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
    """在执行仍在运行时按执行 ID 发起中断。"""
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
    """中断当前绑定在指定会话上的活跃执行。"""
    try:
        return await manager.interrupt_session(session_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/debug/raw-model/stream")
async def debug_raw_model_stream(
    request_body: RawModelStreamRequest,
) -> StreamingResponse:
    """绕过 Agent 运行时，直接代理上游模型流用于调试。"""
    config = AppConfig.from_env()

    async def event_generator() -> AsyncGenerator[str, None]:
        """将上游模型分片持续输出为 SSE 事件，直到流结束。"""
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
        except Exception as exc:  # noqa: BLE001 - 调试流需要向外返回原始异常信息
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

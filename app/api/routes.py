"""HTTP 路由模块。

该模块提供会话创建、流式聊天、中断、状态查询与原始模型调试接口。
"""

from __future__ import annotations

import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from openai import AsyncClient

from app.agent.session_manager import AgentSessionManager, SessionNotFoundError
from app.config import AppConfig
from app.schemas import (
    ChatStreamRequest,
    InterruptResponse,
    RawModelStreamRequest,
    SessionCreateResponse,
    SessionStatusResponse,
)

router = APIRouter(prefix="/v1", tags=["agent"])


def _to_sse_data(event: dict) -> str:
    """将事件字典格式化为 SSE 数据块。

    参数:
        event: 标准事件字典。

    返回:
        str: SSE 协议文本。
    """
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def get_session_manager(request: Request) -> AgentSessionManager:
    """获取会话管理器依赖。

    参数:
        request: FastAPI 请求对象。

    返回:
        AgentSessionManager: 当前应用实例绑定的管理器。
    """
    manager = getattr(request.app.state, "session_manager", None)
    if manager is None:
        config = AppConfig.from_env()
        manager = AgentSessionManager(config=config)
        request.app.state.session_manager = manager
    return manager


@router.post("/sessions", response_model=SessionCreateResponse)
def create_session(
    manager: AgentSessionManager = Depends(get_session_manager),
) -> SessionCreateResponse:
    """创建新会话。

    参数:
        manager: 会话管理器依赖。

    返回:
        SessionCreateResponse: 创建结果。
    """
    session_id = manager.create_session()
    return SessionCreateResponse(session_id=session_id)


@router.get("/sessions/{session_id}", response_model=SessionStatusResponse)
def get_session_status(
    session_id: str,
    manager: AgentSessionManager = Depends(get_session_manager),
) -> SessionStatusResponse:
    """查询会话状态。

    参数:
        session_id: 会话 ID。
        manager: 会话管理器依赖。

    返回:
        SessionStatusResponse: 会话状态信息。
    """
    try:
        return manager.get_session_status(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/interrupt",
    response_model=InterruptResponse,
)
async def interrupt_session(
    session_id: str,
    manager: AgentSessionManager = Depends(get_session_manager),
) -> InterruptResponse:
    """中断会话当前回复任务。

    参数:
        session_id: 会话 ID。
        manager: 会话管理器依赖。

    返回:
        InterruptResponse: 中断结果。
    """
    try:
        return await manager.interrupt_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/chat/stream")
async def chat_stream(
    session_id: str,
    request_body: ChatStreamRequest,
    manager: AgentSessionManager = Depends(get_session_manager),
) -> StreamingResponse:
    """发起流式聊天。
    该接口直接透传会话管理器产出的原始事件，不对流式块做二次格式化。

    参数:
        session_id: 会话 ID。
        request_body: 聊天请求体。
        manager: 会话管理器依赖。

    返回:
        StreamingResponse: `text/event-stream` 类型响应。
    """
    try:
        manager.ensure_session_exists(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def event_generator() -> AsyncGenerator[str, None]:
        """生成 SSE 事件流。

        返回:
            AsyncGenerator[str, None]: SSE 数据块生成器。
        """
        # 关键控制流：直接透传 manager 产出的事件，不做字段重组。
        async for event in manager.stream_chat(
            session_id=session_id,
            request=request_body,
        ):
            yield _to_sse_data(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/debug/raw-model/stream")
async def debug_raw_model_stream(
    request_body: RawModelStreamRequest,
) -> StreamingResponse:
    """调试接口：直接透传模型原始流式返回。

    该接口不经过 ReActAgent，也不对模型 chunk 做字段级处理，
    用于定位“模型原始返回格式”与“业务层二次处理”之间的边界问题。

    参数:
        request_body: 原始模型调试请求体。

    返回:
        StreamingResponse: 原始模型 chunk 的 SSE 流。
    """
    config = AppConfig.from_env()

    async def event_generator() -> AsyncGenerator[str, None]:
        """生成原始模型 SSE 事件流。"""
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
                    },
                )
            yield _to_sse_data(
                {
                    "event_type": "raw_done",
                    "timestamp": None,
                    "payload": {},
                },
            )
        except Exception as exc:  # noqa: BLE001 - 调试接口保留原始异常
            yield _to_sse_data(
                {
                    "event_type": "raw_error",
                    "timestamp": None,
                    "payload": {"message": str(exc)},
                },
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

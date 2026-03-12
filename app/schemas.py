"""HTTP API 数据模型模块。

该模块定义路由请求/响应结构和结构化输出模型。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ResponseMode(str, Enum):
    """聊天响应模式。

    `text` 表示自然语言输出，`task_result` 表示固定 schema 结构化输出。
    """

    TEXT = "text"
    TASK_RESULT = "task_result"


class SessionCreateResponse(BaseModel):
    """创建会话接口响应。"""

    session_id: str = Field(description="服务端生成的会话标识。")


class ChatStreamRequest(BaseModel):
    """流式聊天接口请求体。"""

    message: str = Field(
        min_length=1,
        description="用户输入消息。",
    )
    response_mode: ResponseMode = Field(
        default=ResponseMode.TEXT,
        description="响应模式，支持 text 或 task_result。",
    )
    access_param: str = Field(
        min_length=1,
        description="请求参数，用于验证会话权限，传递key。",
    )


class RawModelStreamRequest(BaseModel):
    """原始模型流调试请求体。"""

    message: str = Field(
        min_length=1,
        description="发送给模型的原始用户消息。",
    )


class SessionStatusResponse(BaseModel):
    """会话状态查询接口响应。"""

    session_id: str = Field(description="会话标识。")
    status: str = Field(description="会话状态：idle、running 或 interrupted。")
    updated_at: datetime = Field(description="会话状态最后更新时间。")
    last_result: dict | None = Field(
        default=None,
        description="最近一次完整回复结果。",
    )


class InterruptResponse(BaseModel):
    """会话中断接口响应。"""

    session_id: str = Field(description="会话标识。")
    interrupted: bool = Field(description="是否成功触发中断。")
    status: str = Field(description="中断请求后会话状态。")


class TaskResultSchema(BaseModel):
    """固定结构化输出模型。

    该模型用于 `response_mode=task_result` 时约束智能体输出。
    """

    summary: str = Field(
        description="任务结果摘要。",
    )
    actions: list[str] = Field(
        default_factory=list,
        description="已经执行或建议执行的动作列表。",
    )
    risks: list[str] = Field(
        default_factory=list,
        description="本次任务中的风险或注意事项。",
    )
    next_steps: list[str] = Field(
        default_factory=list,
        description="建议的下一步行动。",
    )

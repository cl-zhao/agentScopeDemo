"""用于调用方归因的 LiteLLM 请求上下文辅助工具。"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Mapping

from agentscope.model import OpenAIChatModel

NAME_IDENTIFIER_CLAIM = (
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"
)
TENANT_ID_CLAIM = "http://www.aspnetboilerplate.com/identity/claims/tenantId"


@dataclass(frozen=True)
class LiteLLMRequestContext:
    """附加到单次模型调用上的请求级归因字段。"""

    tenant_id: str
    user_id: str
    end_user_id: str
    app_request_id: str
    agentscope_session_id: str
    execution_id: str


_CURRENT_LITELLM_REQUEST_CONTEXT: ContextVar[LiteLLMRequestContext | None] = (
    ContextVar("current_litellm_request_context", default=None)
)


def _read_required_principal_value(
    principal: Mapping[str, Any],
    *keys: str,
) -> str:
    """从候选字段列表中读取第一个非空的 principal 声明值。"""
    for key in keys:
        value = principal.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"Missing required principal fields: {', '.join(keys)}")


def build_litellm_request_context(
    principal: Mapping[str, Any],
    *,
    session_id: str,
    execution_id: str,
    app_request_id: str,
) -> LiteLLMRequestContext:
    """将调用方 principal 信息转换为 LiteLLM 归因上下文。"""
    tenant_id = _read_required_principal_value(
        principal,
        TENANT_ID_CLAIM,
        "tenant_id",
        "tenantId",
    )
    user_id = _read_required_principal_value(
        principal,
        NAME_IDENTIFIER_CLAIM,
        "user_id",
        "userId",
        "sub",
    )
    return LiteLLMRequestContext(
        tenant_id=tenant_id,
        user_id=user_id,
        end_user_id=f"{tenant_id}:{user_id}",
        app_request_id=app_request_id,
        agentscope_session_id=session_id,
        execution_id=execution_id,
    )


def get_current_litellm_request_context() -> LiteLLMRequestContext | None:
    """返回当前异步调用链绑定的请求上下文。"""
    return _CURRENT_LITELLM_REQUEST_CONTEXT.get()


def set_current_litellm_request_context(
    context: LiteLLMRequestContext,
) -> Token[LiteLLMRequestContext | None]:
    """将请求上下文绑定到当前异步调用链，并返回重置令牌。"""
    return _CURRENT_LITELLM_REQUEST_CONTEXT.set(context)


def reset_current_litellm_request_context(
    token: Token[LiteLLMRequestContext | None],
) -> None:
    """使用已保存的令牌恢复上一个 LiteLLM 请求上下文。"""
    _CURRENT_LITELLM_REQUEST_CONTEXT.reset(token)


class ContextAwareOpenAIChatModel(OpenAIChatModel):
    """为每次兼容 OpenAI 的模型调用注入请求级 LiteLLM 字段。"""

    async def __call__(self, *args: Any, **kwargs: Any):
        """附加当前请求元数据后继续转发一次模型调用。"""
        context = get_current_litellm_request_context()
        if context is not None:
            kwargs = self._inject_request_context(kwargs, context)
        return await super().__call__(*args, **kwargs)

    @staticmethod
    def _inject_request_context(
        kwargs: dict[str, Any],
        context: LiteLLMRequestContext,
    ) -> dict[str, Any]:
        """将归因请求头和元数据合并到模型调用参数中。"""
        merged_kwargs = dict(kwargs)

        extra_headers = merged_kwargs.get("extra_headers")
        merged_headers = dict(extra_headers) if isinstance(extra_headers, dict) else {}
        merged_headers["x-end-user-id"] = context.end_user_id
        merged_headers["x-litellm-session-id"] = context.agentscope_session_id
        merged_kwargs["extra_headers"] = merged_headers

        metadata = merged_kwargs.get("metadata")
        merged_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        # 显式保留 execution_id，便于下游区分同一 session 下的重试或多次执行。
        merged_metadata.update(
            {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "app_request_id": context.app_request_id,
                "agentscope_session_id": context.agentscope_session_id,
                "execution_id": context.execution_id,
            },
        )
        merged_kwargs["metadata"] = merged_metadata
        merged_kwargs["user"] = context.end_user_id
        return merged_kwargs

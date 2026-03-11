"""FastAPI 应用入口模块。

该模块负责创建应用实例、注册路由并暴露健康检查接口。
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from app.agent.session_manager import AgentSessionManager
from app.api.routes import router as agent_router
from app.config import AppConfig


def create_app(
    session_manager: AgentSessionManager | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    """创建 FastAPI 应用实例。

    参数:
        session_manager: 可选会话管理器，便于测试注入。
        config: 可选配置对象，当 session_manager 为空时用于构建默认管理器。

    返回:
        FastAPI: 初始化完成的应用对象。
    """
    app = FastAPI(
        title="AgentScope ReAct HTTP Demo",
        version="0.1.0",
        description="基于 AgentScope ReActAgent 的 SSE 流式 HTTP 服务。",
    )
    app.include_router(agent_router)

    if session_manager is not None:
        app.state.session_manager = session_manager
    elif config is not None:
        app.state.session_manager = AgentSessionManager(config=config)
    else:
        app.state.session_manager = None

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """健康检查接口。

        返回:
            dict[str, str]: 固定健康状态。
        """
        return {"status": "ok"}

    return app


def main() -> None:
    """启动开发服务器。

    返回:
        None。
    """
    app = create_app(config=AppConfig.from_env())
    uvicorn.run(app, host="0.0.0.0", port=8003)


# 该对象用于 `uvicorn app.main:app` 方式直接启动。
app = create_app()


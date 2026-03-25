"""无状态执行引擎的 FastAPI 应用入口。"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as agent_router
from app.config import AppConfig


def create_app(
    execution_manager=None,
    config: AppConfig | None = None,
) -> FastAPI:
    """创建 FastAPI 应用，并可按需注入预构建的执行管理器。"""
    app = FastAPI(
        title="AgentScope Stateless Execution Engine",
        version="0.1.0",
        description="Stateless SSE execution service built on AgentScope ReActAgent.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(agent_router)

    app.state.app_config = config

    if execution_manager is not None:
        app.state.execution_manager = execution_manager
    else:
        # 除非测试注入了假实现，否则延迟到首个请求时再创建管理器。
        app.state.execution_manager = None

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """返回轻量级健康检查结果。"""
        return {"status": "ok"}

    return app


def main() -> None:
    """在完成配置校验后启动本地开发服务器。"""
    _ = AppConfig.from_env()
    app = create_app(config=AppConfig.from_env())
    uvicorn.run(app, host="0.0.0.0", port=8003)


app = create_app()

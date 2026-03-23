"""FastAPI application entrypoint for the stateless execution engine."""

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

    if execution_manager is not None:
        app.state.execution_manager = execution_manager
    else:
        # Defer manager construction until first request unless tests inject a fake.
        app.state.execution_manager = None

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    _ = AppConfig.from_env()
    app = create_app(config=AppConfig.from_env())
    uvicorn.run(app, host="0.0.0.0", port=8003)


app = create_app()

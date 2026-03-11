## AgentScope ReAct HTTP Demo

该项目实现了一个基于 AgentScope 的 `FastAPI + SSE` 单智能体服务，支持：

- 实时中断（`/v1/sessions/{id}/interrupt`）
- 并行工具调用（`parallel_tool_calls=True`）
- 固定 schema 结构化输出（`response_mode=task_result`）
- 内存会话管理（多 session、单 session 串行）
- 受限 Python 工具执行（超时、关键字/模块限制、输出截断）

## 环境变量

在启动前请设置：

- `ARK_API_KEY`
- `ARK_BASE_URL`
- `ARK_MODEL`

可选变量：

- `ARK_TEMPERATURE`（默认 `0.2`）
- `ARK_MAX_TOKENS`
- `PYTHON_TOOL_TIMEOUT`（默认 `10`）
- `PYTHON_TOOL_MAX_CODE_LENGTH`（默认 `4000`）
- `PYTHON_TOOL_MAX_OUTPUT_LENGTH`（默认 `6000`）
- `AGENT_SYSTEM_PROMPT`

## 启动方式

```bash
python main.py
```

或

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 测试

```bash
python -m pytest -q
```

## 原始模型流调试

为排查 SSE 二次处理问题，提供了一个“原始模型直连”调试接口：

- `POST /v1/debug/raw-model/stream`
- Body:

```json
{
  "message": "你好"
}
```

该接口会直接输出 OpenAI SDK 返回的原始 chunk（`model_dump`），不经过 ReActAgent 与业务层事件拆分。

## AgentScope 无状态执行引擎

本项目基于 `FastAPI + SSE + AgentScope ReActAgent` 提供一个无状态 AI 执行服务。

服务端不持久化会话历史。调用方需要在每次请求中携带 `context_package`，并且可以在最终响应中按需获取更新后的 `next_context_package`。

### 核心概念

- `session_id`
  - 由调用方生成和持有的会话关联 ID。
  - 引擎侧用它保证“同一个 session 同时只能有一个活动执行”。

- `execution_id`
  - 由引擎生成的单次执行 ID。
  - 用于查询执行状态和发起中断。

- `access_param`
  - 调用方身份令牌。
  - 用于解析租户/用户身份，并注入请求级 LiteLLM 元数据。

- `context_package`
  - 由调用方维护的上下文包。
  - 包含 `summary`、`state`、`recent_messages` 和 `artifacts`。

### 功能特性

- 通过 `POST /v1/executions/stream` 提供无状态流式执行
- 通过 `POST /v1/executions` 提供可选的非流式执行
- 通过 `GET /v1/executions/{execution_id}` 查询执行状态
- 通过 `POST /v1/executions/{execution_id}/interrupt` 中断执行
- 通过 `POST /v1/sessions/{session_id}/interrupt` 提供兼容会话中断路由
- 通过 `POST /v1/debug/raw-model/stream` 提供上游模型原始流调试能力
- 支持请求级 LiteLLM 归因头和元数据注入
- 支持受限 Python 工具执行

### Context Package

请求体中的主要字段：

- `summary`
  - 压缩后的历史摘要。
- `state`
  - 结构化事实、槽位或工具状态。
- `recent_messages`
  - 最近的高保真消息列表。
- `artifacts`
  - 由调用方保留的工具输出或其他原始载荷。

示例：

```json
{
  "session_id": "order-chat-123",
  "access_param": "opaque-token",
  "return_context_package": true,
  "context_package": {
    "version": "1.0",
    "summary": "User is checking order A-1",
    "state": {
      "facts": {
        "order_id": "A-1"
      }
    },
    "recent_messages": [],
    "artifacts": []
  },
  "current_input": {
    "role": "user",
    "content": "What is the shipping status now?"
  }
}
```

### 请求示例

标准 OpenAI 风格参数直接放在顶层，只有模型服务商私有透传参数放进 `provider_params`。

`POST /v1/executions/stream` 示例：

```bash
curl -N -X POST "http://127.0.0.1:8000/v1/executions/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "order-chat-123",
    "access_param": "opaque-token",
    "response_mode": "text",
    "return_context_package": true,
    "context_package": {
      "version": "1.0",
      "summary": "User is checking order A-1",
      "state": {
        "facts": {
          "order_id": "A-1"
        }
      },
      "recent_messages": [],
      "artifacts": []
    },
    "current_input": {
      "role": "user",
      "content": "What is the latest shipping status?"
    },
    "parallel_tool_calls": false,
    "reasoning_effort": "high",
    "response_format": {
      "type": "json_schema",
      "json_schema": {
        "name": "shipping_status",
        "schema": {
          "type": "object",
          "properties": {
            "status": {
              "type": "string"
            }
          },
          "required": ["status"]
        }
      }
    },
    "provider_params": {
      "top_k": 32,
      "repetition_penalty": 1.05
    }
  }'
```

等价 JSON 请求体：

```json
{
  "session_id": "order-chat-123",
  "access_param": "opaque-token",
  "response_mode": "text",
  "return_context_package": true,
  "context_package": {
    "version": "1.0",
    "summary": "User is checking order A-1",
    "state": {
      "facts": {
        "order_id": "A-1"
      }
    },
    "recent_messages": [],
    "artifacts": []
  },
  "current_input": {
    "role": "user",
    "content": "What is the latest shipping status?"
  },
  "parallel_tool_calls": false,
  "reasoning_effort": "high",
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "shipping_status",
      "schema": {
        "type": "object",
        "properties": {
          "status": {
            "type": "string"
          }
        },
        "required": ["status"]
      }
    }
  },
  "provider_params": {
    "top_k": 32,
    "repetition_penalty": 1.05
  }
}
```

说明：

- 顶层标准 OpenAI 参数和 `provider_params` 不能出现同名字段。
- 调用方不要再传 `openai_params` 或 `allowed_openai_params`，引擎会在内部按需归类和生成。
- `provider_params` 会通过 `extra_body` 下发，因此 `top_k`、`repetition_penalty` 这类服务商私有参数应放在这里。

### SSE 事件顺序

典型流式事件顺序如下：

1. `execution_started`
2. 零个或多个 `thinking_chunk`
3. 零个或多个 `assistant_chunk`
4. 零个或多个 `tool_call`
5. 可选的 `interrupted`
6. `final`

当 `return_context_package=true` 时，`final.payload` 中可能包含 `next_context_package`。

### 必填环境变量

- `MODEL_API_KEY`
- `MODEL_BASE_URL`
- `MODEL_NAME`

### 可选环境变量

- `REDIS_URL`
- `REDIS_KEY_PREFIX`
- `EXECUTION_RECORD_TTL_SECONDS`
- `SESSION_ACTIVE_TTL_SECONDS`
- `CONTEXT_RECENT_MESSAGE_LIMIT`
- `CONTEXT_ARTIFACT_CHAR_BUDGET`
- `ARK_TEMPERATURE`
- `ARK_MAX_TOKENS`
- `PYTHON_TOOL_TIMEOUT`
- `PYTHON_TOOL_MAX_CODE_LENGTH`
- `PYTHON_TOOL_MAX_OUTPUT_LENGTH`
- `AGENT_SYSTEM_PROMPT`
- `MCP_SERVICES_HOST`
- `MCP_SERVICES_TRANSPORT`
- `SQLSERVER_CONNECTION_STRING`
- `SQLSERVER_MAX_ROWS`
- `SQLSERVER_QUERY_TIMEOUT`

### LiteLLM 归因信息

每次执行都会向上游模型请求注入调用方归因信息：

- `x-end-user-id: <tenant_id>:<user_id>`
- `x-litellm-session-id: <session_id>`
- `user: <tenant_id>:<user_id>`
- `metadata.tenant_id`
- `metadata.user_id`
- `metadata.app_request_id`
- `metadata.agentscope_session_id`
- `metadata.execution_id`

### 启动方式

```bash
python main.py
```

或者：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 测试

```bash
python -m pytest -q
```

### 原始模型流调试

如果需要绕过 Agent 执行链路，直接观察 OpenAI 兼容接口返回的原始流，可调用：

- `POST /v1/debug/raw-model/stream`

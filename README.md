## AgentScope Stateless Execution Engine

This project exposes a stateless AI execution service built on `FastAPI + SSE + AgentScope ReActAgent`.

The service does not persist conversation history. Callers send a `context_package` on every request and can optionally receive an updated `next_context_package` in the final response.

### Core Concepts

- `session_id`
  - Caller-owned correlation ID.
  - Used to enforce "only one active execution per session" on the engine side.

- `execution_id`
  - Engine-generated identifier for one running request.
  - Used for status queries and interruption.

- `access_param`
  - Caller identity token.
  - Used to derive tenant/user attribution and inject request-scoped LiteLLM metadata.

- `context_package`
  - Caller-managed context envelope.
  - Contains `summary`, `state`, `recent_messages`, and `artifacts`.

### Features

- Stateless execution via `POST /v1/executions/stream`
- Optional non-streaming execution via `POST /v1/executions`
- Execution status query via `GET /v1/executions/{execution_id}`
- Execution interruption via `POST /v1/executions/{execution_id}/interrupt`
- Compatibility interrupt route via `POST /v1/sessions/{session_id}/interrupt`
- Raw upstream model debug stream via `POST /v1/debug/raw-model/stream`
- Request-scoped LiteLLM attribution headers and metadata
- Restricted Python tool execution

### Context Package

Request body fields:

- `summary`
  - Compressed older history.
- `state`
  - Structured facts, slots, or tool state.
- `recent_messages`
  - Most recent full-fidelity turns.
- `artifacts`
  - Raw tool outputs or other caller-retained payloads.

Example:

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

### SSE Event Order

Typical stream order:

1. `execution_started`
2. zero or more `thinking_chunk`
3. zero or more `assistant_chunk`
4. zero or more `tool_call`
5. optional `interrupted`
6. `final`

When `return_context_package=true`, the `final.payload` may include `next_context_package`.

### Required Environment Variables

- `MODEL_API_KEY`
- `MODEL_BASE_URL`
- `MODEL_NAME`

### Optional Environment Variables

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

### LiteLLM Attribution

Each execution injects caller attribution into upstream model requests:

- `x-end-user-id: <tenant_id>:<user_id>`
- `x-litellm-session-id: <session_id>`
- `user: <tenant_id>:<user_id>`
- `metadata.tenant_id`
- `metadata.user_id`
- `metadata.app_request_id`
- `metadata.agentscope_session_id`
- `metadata.execution_id`

### Run

```bash
python main.py
```

or

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Test

```bash
python -m pytest -q
```

### Raw Model Debug Stream

To inspect the raw OpenAI-compatible stream without passing through the ReAct execution pipeline:

- `POST /v1/debug/raw-model/stream`

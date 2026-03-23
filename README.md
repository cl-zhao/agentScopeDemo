## AgentScope ReAct HTTP Demo

This project provides a single-agent HTTP service based on `FastAPI + SSE`.

Features:

- Session creation and in-memory session management
- Streaming chat via `/v1/sessions/{id}/chat/stream`
- Session interruption via `/v1/sessions/{id}/interrupt`
- Parallel tool execution inside the agent
- Structured output mode with `response_mode=task_result`
- Restricted Python tool execution

## Required Environment Variables

Set these before starting the service:

- `ARK_API_KEY`
- `ARK_BASE_URL`
- `ARK_MODEL`

Optional:

- `ARK_TEMPERATURE` (default `0.2`)
- `ARK_MAX_TOKENS`
- `PYTHON_TOOL_TIMEOUT` (default `10`)
- `PYTHON_TOOL_MAX_CODE_LENGTH` (default `4000`)
- `PYTHON_TOOL_MAX_OUTPUT_LENGTH` (default `6000`)
- `AGENT_SYSTEM_PROMPT`

## Model Request Config

Gateway passthrough settings are no longer read from environment variables.
They are loaded from:

- `config/model_request.toml`

Example:

```toml
[default]
allowed_openai_params = []
extra_body = {}

[models."doubao-seed-2-0-mini-260215"]
allowed_openai_params = ["parallel_tool_calls"]
extra_body = {}
```

Rules:

- `default` applies to all models
- `models."<model_name>"` overrides and extends `default`
- `allowed_openai_params` is merged into `extra_body.allowed_openai_params`

## LiteLLM Usage Attribution

When this service calls an OpenAI-compatible LiteLLM gateway, each model
request now includes request-scoped usage identifiers derived from the current
`access_param` principal:

- `x-end-user-id: <tenant_id>:<user_id>`
- `x-litellm-session-id: <agentscope_session_id>`
- `user: <tenant_id>:<user_id>`
- `metadata.tenant_id`
- `metadata.user_id`
- `metadata.app_request_id`
- `metadata.agentscope_session_id`

To let LiteLLM attribute spend by end user, configure the proxy with:

```yaml
general_settings:
  user_header_name: "x-end-user-id"
```

Recommended query dimensions in LiteLLM:

- `end_user` for per-user / per-tenant-user usage
- `session_id` for per-conversation correlation
- `metadata.app_request_id` for grouping multiple LiteLLM calls triggered by one
  AgentScope request

## Run

```bash
python main.py
```

or

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Test

```bash
python -m pytest -q
```

## Raw Model Debug Stream

To inspect the raw OpenAI-compatible stream without passing through the ReAct
agent pipeline:

- `POST /v1/debug/raw-model/stream`

Body:

```json
{
  "message": "你好"
}
```

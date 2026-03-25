# LiteLLM Allowed OpenAI Params Middleware Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the LiteLLM request-compatibility path so the engine accepts request-level valued `allowed_openai_params`, generates the gateway allowlist automatically, and stops requiring per-model repeated passthrough configuration.

**Architecture:** Split the work into three units: config parsing, request/schema plumbing, and LiteLLM request assembly. Introduce a structured model-request config object, carry request-level passthrough params through the execution pipeline, and centralize final `generate_kwargs` assembly in one runtime builder path so precedence and validation remain explicit.

**Tech Stack:** Python 3.13, Pydantic, FastAPI, agentscope/ReActAgent, pytest

---

## File Structure

**Create**
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\agent\request_params.py`
  Purpose: Build final LiteLLM `generate_kwargs`, merge request-level valued passthrough params, and generate `extra_body.allowed_openai_params`.

**Modify**
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\config\model_request.toml`
  Purpose: Replace the old per-model `allowed_openai_params` shape with `global/default/models` schema.
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\config.py`
  Purpose: Parse the new TOML shape into a structured runtime config object instead of flattening directly into `model_extra_body`.
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\schemas.py`
  Purpose: Add request-level valued `allowed_openai_params` to `ExecutionStreamRequest` and validate reserved-field blocking.
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\manager.py`
  Purpose: Pass request-level valued passthrough params into agent creation so runtime precedence can be honored.
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\agent\factory.py`
  Purpose: Stop assembling LiteLLM request kwargs inline and delegate to the new runtime builder.
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\api\routes.py`
  Purpose: Wire any new config object construction and keep request validation / error shape aligned with FastAPI behavior.

**Test**
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_config.py`
  Purpose: Validate the new `model_request.toml` schema parsing, merge semantics, and config-level error conditions.
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_schemas.py`
  Purpose: Validate request-level `allowed_openai_params` typing and reserved-field blocking.
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_factory.py`
  Purpose: Validate final `generate_kwargs` assembly, precedence, and allowlist generation.
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_execution_manager.py`
  Purpose: Validate request-level passthrough params make it from the execution request into agent creation.
- `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_api_executions.py`
  Purpose: Validate the public API accepts the new field and rejects invalid/reserved-key usage.

## Chunk 1: Config Model and Schema Surface

### Task 1: Define the New TOML Contract in Tests First

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_config.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\config\model_request.toml`

- [ ] Step 1: Add a failing config test that writes a temporary TOML file using the new `[global]`, `[default]`, and `[models."<name>"]` schema.
  Test expectations:
  - `global.compat_allowed_openai_params` is parsed as a string list.
  - `global.non_overridable_request_params` is parsed as a string list.
  - `default.model_params` and model-specific `model_params` merge with model values winning.
  - model-level `extra_allowed_openai_params` and `blocked_allowed_openai_params` remain distinct from `extra_body`.

- [ ] Step 2: Add failing config tests for invalid schema cases.
  Cover at least:
  - `model_params` is not a TOML table.
  - `extra_body` is not a TOML table.
  - a parameter appears in both `extra_allowed_openai_params` and `blocked_allowed_openai_params`.
  - `compat_allowed_openai_params` or `non_overridable_request_params` is not a string array.

- [ ] Step 3: Run the focused config tests and confirm they fail for the missing schema support.
  Run: `python -m pytest tests/test_config.py -q`
  Expected: FAIL with assertions or validation errors tied to the old config parser.

- [ ] Step 4: Replace the checked-in `config/model_request.toml` sample with the new schema from the spec.
  Minimum sample contents:
  - `global.compat_allowed_openai_params` contains current engine-emitted `parallel_tool_calls`.
  - `global.compat_allowed_openai_params` also includes the initial domestic-model compatibility set from the spec.
  - `default/model` sections use the new field names only.

- [ ] Step 5: Commit the test-and-config-contract baseline.
  Run:
  ```bash
  git add tests/test_config.py config/model_request.toml
  git commit -m "test: define LiteLLM middleware config contract"
  ```

### Task 2: Parse the New Config Shape into a Structured Runtime Object

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\config.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_config.py`

- [ ] Step 1: Add failing assertions in `tests/test_config.py` for the new runtime object shape on `AppConfig`.
  Assert at least:
  - `AppConfig` exposes a structured `model_request_config` object instead of only a flattened `model_extra_body`.
  - the object contains merged `global`, `model_params`, allowlist-add, allowlist-block, and `extra_body` data.
  - `parallel_tool_calls` is no longer expected to arrive only through `extra_body.allowed_openai_params`.

- [ ] Step 2: Run only the config tests again to confirm the new assertions fail before code changes.
  Run: `python -m pytest tests/test_config.py -q`
  Expected: FAIL because `AppConfig` still returns the old flattened structure.

- [ ] Step 3: Refactor `app/config.py` to produce a structured runtime config object.
  Implementation requirements:
  - keep TOML parsing in `app/config.py` unless a helper type is clearly needed there.
  - add explicit validators/helpers for `global`, `default`, and `models."<name>"`.
  - normalize missing sections to empty lists / dicts.
  - reject overlapping allow/block entries in the same effective config layer.
  - update `AppConfig` to expose `model_request_config` and remove or stop using `model_extra_body`.

- [ ] Step 4: Re-run the focused config tests and confirm they pass.
  Run: `python -m pytest tests/test_config.py -q`
  Expected: PASS.

- [ ] Step 5: Commit the config parser refactor.
  Run:
  ```bash
  git add app/config.py tests/test_config.py
  git commit -m "feat: parse structured LiteLLM request config"
  ```

## Chunk 2: Public Request Contract and Validation

### Task 3: Add Request-Level Valued `allowed_openai_params` to the Public API

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\schemas.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_schemas.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_api_executions.py`

- [ ] Step 1: Add failing schema tests for the new request field.
  Cover at least:
  - `ExecutionStreamRequest` accepts `allowed_openai_params` as `dict[str, Any]`.
  - omitting the field still works.
  - passing a list instead of an object fails validation.

- [ ] Step 2: Add failing API tests for reserved-field blocking.
  Cover at least:
  - request body containing `allowed_openai_params = { "model": "x" }` is rejected.
  - request body containing `allowed_openai_params = { "messages": [] }` is rejected.
  - the response status matches the existing FastAPI/Pydantic validation style used by the project.

- [ ] Step 3: Run the targeted schema and API tests to confirm they fail first.
  Run:
  ```bash
  python -m pytest tests/test_schemas.py tests/test_api_executions.py -q
  ```
  Expected: FAIL because the request model does not yet expose or validate the field.

- [ ] Step 4: Update `app/schemas.py` to add valued `allowed_openai_params` and enforce reserved-field blocking.
  Implementation requirements:
  - the field should default to an empty dict.
  - validation should reject keys listed in `global.non_overridable_request_params`.
  - validation should keep the external API surface to one field only; do not introduce a second request-level passthrough field.

- [ ] Step 5: Re-run the targeted schema and API tests and confirm they pass.
  Run:
  ```bash
  python -m pytest tests/test_schemas.py tests/test_api_executions.py -q
  ```
  Expected: PASS.

- [ ] Step 6: Commit the public request-contract change.
  Run:
  ```bash
  git add app/schemas.py tests/test_schemas.py tests/test_api_executions.py
  git commit -m "feat: add valued request-level LiteLLM passthrough params"
  ```

## Chunk 3: Runtime Assembly and Precedence

### Task 4: Centralize LiteLLM Request Assembly in a Dedicated Builder

**Files:**
- Create: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\agent\request_params.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_factory.py`

- [ ] Step 1: Add failing factory tests that describe the final merge behavior.
  Cover at least:
  - request-level valued `allowed_openai_params` overrides config/default values.
  - `parallel_tool_calls` from request-level params overrides the engine default.
  - request-level keys are included in `extra_body.allowed_openai_params`.
  - `extra_body` merges provider-private fields without losing generated allowlist entries.
  - blocked allowlist entries are removed from the final allowlist, unless they are required by request-level passthrough semantics and the design says request-level wins.

- [ ] Step 2: Run the focused factory tests and confirm they fail under the current inline assembly path.
  Run: `python -m pytest tests/test_factory.py -q`
  Expected: FAIL because `AgentFactory` still hardcodes `parallel_tool_calls` and forwards only `model_extra_body`.

- [ ] Step 3: Create `app/agent/request_params.py` and implement a single builder function or small builder class.
  It should:
  - accept engine defaults, structured `model_request_config`, and request-level valued passthrough params.
  - merge actual parameter values with request-level precedence.
  - generate the final `allowed_openai_params` string list for LiteLLM.
  - merge `extra_body` safely.
  - reject or surface invalid reserved-key attempts only if the schema layer somehow missed them.

- [ ] Step 4: Update `app/agent/factory.py` to delegate request assembly to the new builder.
  Implementation requirements:
  - stop manually constructing `generate_kwargs` inline beyond the builder inputs.
  - keep `ReActAgent(..., parallel_tool_calls=...)` in sync with the final effective value chosen by the builder.
  - remove the dependency on the old `model_extra_body` field.

- [ ] Step 5: Re-run the factory tests and confirm they pass.
  Run: `python -m pytest tests/test_factory.py -q`
  Expected: PASS.

- [ ] Step 6: Commit the runtime builder extraction.
  Run:
  ```bash
  git add app/agent/request_params.py app/agent/factory.py tests/test_factory.py
  git commit -m "feat: centralize LiteLLM request param assembly"
  ```

### Task 5: Thread Request-Level Params Through the Execution Path

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\manager.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\agent\factory.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_execution_manager.py`

- [ ] Step 1: Add failing execution-manager tests proving request-level valued passthrough params reach agent creation.
  Cover at least:
  - the manager passes `ExecutionStreamRequest.allowed_openai_params` into the factory path.
  - request-level overrides are visible in the agent/model kwargs used for execution.
  - request bodies without the field still follow the existing path unchanged.

- [ ] Step 2: Run the targeted execution-manager tests and confirm they fail before plumbing changes.
  Run: `python -m pytest tests/test_execution_manager.py -k allowed_openai_params -q`
  Expected: FAIL because `create_agent()` currently takes no request-specific param input.

- [ ] Step 3: Modify `app/execution/manager.py` and `app/agent/factory.py` so the execution path passes the request-level valued passthrough params into runtime assembly.
  Implementation requirements:
  - prefer a small signature change over hidden globals.
  - keep the no-request-override path simple, using `{}` by default.

- [ ] Step 4: Re-run the targeted execution-manager tests and confirm they pass.
  Run: `python -m pytest tests/test_execution_manager.py -k allowed_openai_params -q`
  Expected: PASS.

- [ ] Step 5: Commit the execution plumbing.
  Run:
  ```bash
  git add app/execution/manager.py app/agent/factory.py tests/test_execution_manager.py
  git commit -m "feat: plumb request-level LiteLLM passthrough params"
  ```

## Chunk 4: Error Surfaces, Logging, and Regression Coverage

### Task 6: Add Focused Diagnostics for Final Param Origin and Allowlist

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\agent\factory.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\manager.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_factory.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_execution_manager.py`

- [ ] Step 1: Add failing tests or assertions for lightweight diagnostics.
  Cover at least:
  - final allowlist keys can be observed without dumping sensitive payload values.
  - the runtime path can expose which request-level keys overrode defaults.
  - errors from LiteLLM compatibility failures retain enough context to diagnose missing allowlist entries.

- [ ] Step 2: Run the focused factory/manager tests and confirm the diagnostics are missing today.
  Run:
  ```bash
  python -m pytest tests/test_factory.py tests/test_execution_manager.py -q
  ```
  Expected: FAIL or missing assertions for diagnostic metadata/log shape.

- [ ] Step 3: Add minimal structured diagnostics in the runtime path.
  Minimum diagnostics:
  - request-level passthrough keys
  - final allowlist keys
  - overridden keys
  - final `extra_body` top-level keys
  Keep values redacted or summarized rather than logged verbatim.

- [ ] Step 4: Re-run the focused diagnostics tests and confirm they pass.
  Run:
  ```bash
  python -m pytest tests/test_factory.py tests/test_execution_manager.py -q
  ```
  Expected: PASS.

- [ ] Step 5: Commit the diagnostics layer.
  Run:
  ```bash
  git add app/agent/factory.py app/execution/manager.py tests/test_factory.py tests/test_execution_manager.py
  git commit -m "feat: add LiteLLM passthrough diagnostics"
  ```

### Task 7: Full Regression Verification

**Files:**
- No code changes expected

- [ ] Step 1: Run the focused suite for the touched units.
  Run:
  ```bash
  python -m pytest tests/test_config.py tests/test_schemas.py tests/test_factory.py tests/test_api_executions.py tests/test_execution_manager.py -q
  ```
  Expected: PASS, except for any pre-existing async skips already known in this repository.

- [ ] Step 2: If the focused suite passes, run the broader regression tests around execution and context handling.
  Run:
  ```bash
  python -m pytest tests/test_context_package.py tests/test_context_compiler.py tests/test_execution_registry.py tests/test_execution_store.py -q
  ```
  Expected: PASS.

- [ ] Step 3: Review the final diff to confirm the scope stayed inside:
  - model request config parsing
  - public request contract
  - LiteLLM request assembly
  - diagnostics and validation

- [ ] Step 4: Prepare the final integration commit.
  Run:
  ```bash
  git status --short
  git add app/config.py app/schemas.py app/agent/request_params.py app/agent/factory.py app/execution/manager.py app/api/routes.py config/model_request.toml tests/test_config.py tests/test_schemas.py tests/test_factory.py tests/test_api_executions.py tests/test_execution_manager.py
  git commit -m "feat: add LiteLLM middleware passthrough param support"
  ```

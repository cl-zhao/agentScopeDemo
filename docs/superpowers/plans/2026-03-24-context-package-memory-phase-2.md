# Context Package Memory Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement phase 2 summary compression so buffered evicted messages are periodically folded into a sectioned `summary` with configurable limits.

**Architecture:** Extend the current phase 1 updater with a deterministic summary compressor that only runs when `summary_buffer` reaches configured flush thresholds. Add configuration for summary formatting limits, keep the summary buffer if compression fails, and clear it only after successful compression.

**Tech Stack:** Python 3.13, Pydantic, FastAPI, pytest

---

### Task 1: Config Surface for Summary Compression

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\config.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_config.py`

- [ ] Step 1: Add failing tests for summary compression formatting limits exposed through config.
- [ ] Step 2: Run targeted config tests and confirm they fail for missing fields.
- [ ] Step 3: Add the config fields and env loading logic.
- [ ] Step 4: Re-run targeted config tests and confirm they pass.

### Task 2: Summary Compression Logic

**Files:**
- Create: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\memory_summary.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\context_package.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_context_package.py`

- [ ] Step 1: Add failing tests for summary flush, sectioned output, revision bump, and buffer clearing on successful compression.
- [ ] Step 2: Run the targeted summary tests and confirm they fail for the intended missing behavior.
- [ ] Step 3: Implement a deterministic summary compressor with configurable formatting limits.
- [ ] Step 4: Re-run the targeted summary tests and confirm they pass.

### Task 3: Runtime Wiring

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\api\routes.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_execution_manager.py`

- [ ] Step 1: Add or update a failing runtime test proving flushed buffers become summary output in returned `next_context_package`.
- [ ] Step 2: Run the targeted runtime test and confirm it fails for missing wiring.
- [ ] Step 3: Pass the new config values into the updater/compressor construction path.
- [ ] Step 4: Re-run the runtime test and confirm it passes.

### Task 4: Verification

**Files:**
- No code changes expected

- [ ] Step 1: Run focused tests for config, context package, schemas, and execution manager.
- [ ] Step 2: Run the broader execution/API regression tests affected by the updater.
- [ ] Step 3: Review the diff to confirm no unrelated behavior changed.

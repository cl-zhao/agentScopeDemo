# Context Package Memory Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement phase 1 of context memory updates so the engine returns normalized state, memory metadata, recent-message windowing, and buffered evicted messages with configurable thresholds.

**Architecture:** Extend `ContextPackage` with engine-managed memory metadata, replace the current append-only updater with deterministic state extraction/reduction and recent-window buffering, and expose all tunable thresholds through `AppConfig`. Phase 1 does not update `summary`; it prepares the data path needed for low-frequency summary compression in phase 2.

**Tech Stack:** Python 3.13, Pydantic, FastAPI, pytest

---

### Task 1: Config and Schema Surface

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\config.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\schemas.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_config.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_schemas.py`

- [ ] Step 1: Add failing tests for configurable summary-buffer settings and memory-meta schema support.
- [ ] Step 2: Run the targeted tests and verify they fail for the intended missing behavior.
- [ ] Step 3: Add the config fields and schema models with backward-compatible defaults.
- [ ] Step 4: Re-run the targeted tests and verify they pass.

### Task 2: Deterministic Memory Update Components

**Files:**
- Create: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\memory_state.py`
- Create: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\memory_window.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\context_package.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_context_package.py`

- [ ] Step 1: Add failing tests for normalized state, tool-derived state updates, recent-message eviction, and summary-buffer accumulation.
- [ ] Step 2: Run those tests and verify they fail for the intended missing behavior.
- [ ] Step 3: Implement minimal state normalization, deterministic observation extraction, reducer logic, and window/buffer management.
- [ ] Step 4: Re-run the targeted tests and verify they pass.

### Task 3: Runtime Wiring

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\api\routes.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_execution_manager.py`

- [ ] Step 1: Add a failing test proving the execution manager returns `next_context_package` with the new memory fields.
- [ ] Step 2: Run the targeted test and verify it fails for the intended missing wiring.
- [ ] Step 3: Wire the new config values into `ContextPackageUpdater` construction.
- [ ] Step 4: Re-run the targeted test and verify it passes.

### Task 4: Verification

**Files:**
- No code changes expected

- [ ] Step 1: Run focused test files for config, schemas, context package, and execution manager.
- [ ] Step 2: Run the broader relevant suite for execution-related tests.
- [ ] Step 3: Review diffs for accidental behavior changes before close-out.

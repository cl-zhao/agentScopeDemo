# Context Package Memory Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement phase 3 state intelligence so the engine can extract user-declared order facts, conservatively backfill assistant-labeled facts, and convert unresolved conflicts into bounded `task.pending_questions`.

**Architecture:** Keep the phase 1/2 memory pipeline intact and extend only the deterministic state path. Add configurable caps for pending-question accumulation, teach `StateObservationExtractor` to read user messages and conservative assistant label/value pairs, and teach `StateReducer` field-specific conflict rules for order/logistics facts. Tool-derived facts remain highest priority and can resolve previously pending conflicts.

**Tech Stack:** Python 3.13, Pydantic, FastAPI, pytest

---

### Task 1: Config Surface for Phase 3 State Controls

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\config.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\api\routes.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_config.py`

- [ ] Step 1: Add failing tests for phase 3 state-control settings exposed through env-backed config.
- [ ] Step 2: Run the targeted config tests and confirm they fail for missing fields.
- [ ] Step 3: Add bounded pending-question configuration and wire it into `ContextPackageUpdater`.
- [ ] Step 4: Re-run the targeted config tests and confirm they pass.

### Task 2: State Extraction and Conflict Tests

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_context_package.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\tests\test_execution_manager.py`

- [ ] Step 1: Add failing tests for user-declared order/tracking extraction from `current_input`.
- [ ] Step 2: Add failing tests for conservative assistant label/value extraction from `final_text`.
- [ ] Step 3: Add failing tests proving conflicting assistant state updates become bounded `task.pending_questions`, and later tool results can resolve them.
- [ ] Step 4: Run the targeted tests and confirm they fail for the intended missing behavior.

### Task 3: Deterministic Phase 3 State Logic

**Files:**
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\memory_state.py`
- Modify: `F:\agentScope_demo\demo\.worktrees\stateless-ai-execution-engine\app\execution\context_package.py`

- [ ] Step 1: Extend the extractor with deterministic user fact parsing for order/logistics identifiers.
- [ ] Step 2: Extend the extractor with conservative assistant parsing for explicit labeled facts only.
- [ ] Step 3: Add field-aware conflict resolution and bounded pending-question management in `StateReducer`.
- [ ] Step 4: Re-run the targeted phase 3 tests and confirm they pass.

### Task 4: Verification

**Files:**
- No code changes expected

- [ ] Step 1: Run focused tests for config, context package, and execution-manager memory behavior.
- [ ] Step 2: Run the broader execution/API regression tests touched by the updater wiring.
- [ ] Step 3: Review the diff to confirm phase 3 stayed within the planned state-update scope.

# Parameter Passthrough Redesign

> This spec supersedes [2026-03-25-litellm-allowed-openai-params-middleware-design.md](2026-03-25-litellm-allowed-openai-params-middleware-design.md). The older design treated `allowed_openai_params` as part of the external API contract. This redesign removes that coupling.

## 1. Background

The current project sends model requests through a LiteLLM gateway, but the project-level request contract is currently coupled to LiteLLM's internal `allowed_openai_params` behavior.

That coupling has created two concrete problems:

- The external request field named `allowed_openai_params` is actually a valued passthrough object in this project, not LiteLLM's native list-of-names semantics.
- `config/model_request.toml` is currently used to prefill `allowed_openai_params` names, which is unsafe for some providers and model groups.

Recent failures confirmed the issue:

- When `top_k` appears in `allowed_openai_params`, the LiteLLM gateway can end up sending `top_k` to Volcengine in a way that causes `AsyncCompletions.create()` to reject it.
- The same failure pattern also applies to `repetition_penalty`.
- For Volcengine-compatible models, provider-native params such as `top_k` can already be passed through `extra_body`. They do not need to be represented as LiteLLM `allowed_openai_params`.

The current design is therefore unstable. It mixes three different concerns into one mechanism:

- external API contract
- project-level config defaults
- LiteLLM adapter quirks

This redesign separates those concerns.

## 2. Goals

- Define a stable external request contract that does not expose LiteLLM internals.
- Support future provider expansion without reintroducing provider-specific coupling into the public API.
- Allow provider-native params to be passed through exactly as provided by the caller.
- Keep OpenAI-style params and provider-native params on separate paths.
- Stop pre-populating LiteLLM `allowed_openai_params` from config.
- Generate LiteLLM `allowed_openai_params` only when the adapter layer truly needs them.
- Preserve a small amount of model-specific configuration for defaults and protected fields.
- Improve debugging by making parameter source and final placement observable.

## 3. Non-Goals

- No backward compatibility with the current request schema is required.
- No automatic runtime capability detection against provider APIs.
- No provider/model capability registry that attempts to fully model every vendor parameter.
- No silent dropping or auto-renaming of ambiguous parameters.
- No attempt to make LiteLLM behavior uniform across all provider implementations.

## 4. Design Summary

The redesign introduces a strict two-layer request contract:

- `openai_params`: caller-supplied OpenAI-style params
- `provider_params`: caller-supplied provider-native params

And it assigns clear internal routing:

- `openai_params` go to top-level request fields
- `provider_params` go to `extra_body`

`allowed_openai_params` is removed from the external request contract and downgraded to an internal LiteLLM adapter detail.

## 5. External Request Contract

The request schema should expose these fields:

```json
{
  "openai_params": {
    "response_format": {"type": "json_object"},
    "tools": [],
    "reasoning_effort": "high"
  },
  "provider_params": {
    "top_k": 20,
    "repetition_penalty": 1.1
  }
}
```

### 5.1 `openai_params`

Purpose:

- Holds params that are conceptually part of the OpenAI-style request surface.

Examples:

- `temperature`
- `top_p`
- `presence_penalty`
- `frequency_penalty`
- `response_format`
- `tools`
- `tool_choice`
- `reasoning_effort`

Behavior:

- Merged into the final top-level request payload.
- May participate in internal LiteLLM `allowed_openai_params` generation when required by adapter rules.

### 5.2 `provider_params`

Purpose:

- Holds provider-native params that should be passed through exactly as provided.

Examples:

- `top_k`
- `repetition_penalty`
- `min_p`
- provider-specific nested flags

Behavior:

- Never promoted to top-level request fields.
- Always merged into `extra_body`.
- Never used to generate LiteLLM `allowed_openai_params`.

### 5.3 Removed Field

The external request schema must no longer expose:

- `allowed_openai_params`

Reason:

- It is a LiteLLM internal mechanism, not a stable project API concept.

## 6. `model_request.toml` Responsibilities

`config/model_request.toml` should be simplified so it only describes project-level defaults and safeguards, not LiteLLM allowlists.

### 6.1 New Responsibilities

The config file should handle:

- default OpenAI-style params
- default provider-native params
- static provider `extra_body` additions
- protected request keys that cannot be overridden
- a small internal adapter profile for LiteLLM passthrough quirks

### 6.2 Removed Responsibilities

The config file should no longer manage:

- `compat_allowed_openai_params`
- `extra_allowed_openai_params`
- `blocked_allowed_openai_params`

These are all tied to the old idea of predeclaring LiteLLM `allowed_openai_params`, which is exactly what caused the current failures.

### 6.3 Target Config Shape

```toml
[global]
non_overridable_openai_params = [
  "model",
  "messages",
  "stream",
]
non_overridable_provider_params = [
  "allowed_openai_params",
  "extra_body",
]

[default]
openai_defaults = {}
provider_defaults = {}
extra_body = {}
litellm_allowed_openai_passthrough = []

[models."doubao-seed-2-0-mini-260215"]
openai_defaults = {}
provider_defaults = {}
extra_body = {}
litellm_allowed_openai_passthrough = []
```

### 6.4 Field Semantics

- `openai_defaults`
  - Real default values for top-level OpenAI-style params.
- `provider_defaults`
  - Real default values for provider-native params that should land in `extra_body`.
- `extra_body`
  - Static nested provider payload additions that are neither external OpenAI params nor generic provider passthrough params.
- `litellm_allowed_openai_passthrough`
  - A small internal allowlist used only by the LiteLLM adapter when certain top-level OpenAI-style params need to be mirrored into `allowed_openai_params`.

This final field is intentionally narrow. It is not a public feature toggle and not a generic capability registry.

## 7. Request Assembly Pipeline

The final request should be assembled in five stages.

### 7.1 Stage 1: Start From Engine Defaults

Start from engine-owned fields such as:

- `temperature`
- `parallel_tool_calls`
- `max_tokens`

These remain controlled by the engine as they are today.

### 7.2 Stage 2: Apply Config Defaults

Load and merge:

- `openai_defaults`
- `provider_defaults`
- `extra_body`

Model-specific config overrides default config in the usual way.

### 7.3 Stage 3: Apply Request Params

Merge:

- `openai_params` over top-level OpenAI-style defaults
- `provider_params` over provider-native defaults

Request values win over config defaults unless blocked by protection rules.

### 7.4 Stage 4: Build Final Payload

Construct:

- top-level request fields from engine defaults plus merged `openai_params`
- `extra_body` from static config `extra_body` plus merged `provider_params`

Final routing rule:

- top-level = engine defaults + final OpenAI-style params
- `extra_body` = static config additions + final provider-native params

### 7.5 Stage 5: Generate LiteLLM Internal Passthrough Hints

Only after the final top-level param set is known should the adapter consider generating LiteLLM `allowed_openai_params`.

Rules:

- This generation is internal only.
- Only params that are actually present in the final top-level payload may be considered.
- Only params listed in `litellm_allowed_openai_passthrough` may be added.
- No `provider_params` key may ever influence this list.
- No config entry may prefill `allowed_openai_params` without a real top-level value being present in the request.
- If no keys are generated, `extra_body.allowed_openai_params` should be omitted entirely.

This rule directly prevents the current `top_k` and `repetition_penalty` failures.

## 8. Validation Rules

The API and request builder must reject ambiguous or unsafe input with explicit 4xx errors.

### 8.1 Key Collisions

Reject the request if the same key appears in both:

- `openai_params`
- `provider_params`

Reason:

- The final placement would be ambiguous.

### 8.2 Reserved Provider Keys

Reject `provider_params` keys that attempt to control internal transport structure:

- `allowed_openai_params`
- `extra_body`
- any other engine-reserved nested control field

Reason:

- `provider_params` should represent vendor params, not envelope mutation.

### 8.3 Non-Overridable Fields

Reject any caller attempt to override fields protected by:

- `non_overridable_openai_params`
- `non_overridable_provider_params`

### 8.4 Type Validation

Reject invalid shapes for:

- `openai_params`
- `provider_params`
- config sections

The system should fail clearly instead of silently coercing or dropping values.

## 9. Observability and Diagnostics

Each request should produce structured diagnostics that make the final parameter path obvious without logging full sensitive payloads.

Recommended fields:

- `model_name`
- `request_openai_param_keys`
- `request_provider_param_keys`
- `final_top_level_param_keys`
- `final_extra_body_keys`
- `generated_allowed_openai_param_keys`
- `param_sources`

`param_sources` should identify where each final key came from, for example:

```text
temperature <- engine_default
response_format <- request_openai
top_k <- request_provider
thinking <- config_provider_default
```

This is critical for debugging provider mismatches and future LiteLLM behavior changes.

## 10. Error Handling Strategy

The system should prefer explicit failure over silent degradation for request-shape issues.

Return 4xx for:

- schema violations
- protected field overrides
- duplicate key collisions across the two param layers
- reserved transport key usage inside `provider_params`

Allow downstream provider errors to surface normally when:

- the request shape is valid
- the provider rejects a real passed-through parameter

This keeps the project honest about caller intent while avoiding the current self-inflicted LiteLLM allowlist failures.

## 11. Testing Requirements

At minimum, implementation should cover:

### 11.1 Config Parsing

- new config structure loads correctly
- defaults merge correctly across global/default/model layers
- invalid config shapes fail loudly

### 11.2 Request Assembly

- `openai_params` are emitted only at top-level
- `provider_params` are emitted only inside `extra_body`
- provider defaults land in `extra_body`
- static config `extra_body` merges correctly with provider params

### 11.3 LiteLLM Adapter Generation

- `litellm_allowed_openai_passthrough` only applies to actually present top-level params
- no absent key is materialized as `None` solely because its name appears in an allowlist
- `provider_params.top_k` does not generate `allowed_openai_params=["top_k"]`

### 11.4 Validation

- duplicate keys across `openai_params` and `provider_params` fail
- reserved provider keys fail
- non-overridable fields fail

### 11.5 Regression Coverage

- Volcengine request with `provider_params.top_k` builds a valid `extra_body`
- Volcengine request with `provider_params.repetition_penalty` builds a valid `extra_body`
- OpenAI-style params that truly need LiteLLM passthrough still work when listed in `litellm_allowed_openai_passthrough`

## 12. Code Ownership Boundaries

### 12.1 `app/schemas.py`

Responsible for:

- replacing the old external passthrough field with `openai_params` and `provider_params`
- validating basic request shape

### 12.2 `app/config.py`

Responsible for:

- parsing the new `model_request.toml`
- returning merged config objects for defaults, protected fields, and LiteLLM adapter hints

### 12.3 `app/agent/request_params.py`

Responsible for:

- assembling final request payloads from engine defaults, config defaults, and request params
- enforcing collision rules
- generating final `extra_body`
- generating internal LiteLLM `allowed_openai_params` only when required

### 12.4 Execution Entry Path

Responsible for:

- passing through the new request fields unchanged into the request builder
- not reintroducing LiteLLM-specific semantics at the API boundary

## 13. Expected Outcome

After this redesign:

- callers think in terms of OpenAI-style params vs provider-native params
- provider-native params are stably passed through as provider data, not LiteLLM allowlist hints
- LiteLLM `allowed_openai_params` becomes a small internal adapter concern instead of a public project contract
- new provider integrations require less repeated config work
- the current `top_k` and `repetition_penalty` failure class is removed by design

## 14. Implementation Direction

Implementation should be done in one cut, with no backward-compatibility layer:

- replace the external request schema
- replace the config model
- replace the request builder merge logic
- update tests to match the new contract

This is appropriate because the project is a demo and the user explicitly prefers a direct redesign over transitional compatibility.

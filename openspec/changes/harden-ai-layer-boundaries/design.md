## Context

See `proposal.md` for motivation. The current AI layer has correct package-level imports, but `ToolDefinition.from_tool()` and transport helpers inspect arbitrary tool-shaped objects, while `OpenAICompatClient` stores mutable tools on a reusable client. The latter is unsafe for concurrent requests. The same transport file also combines request serialization, retries, streaming framing, and response assembly beyond the repository's size guidance. Catalog parsing intentionally tolerates user edits but does not consistently report every skipped record.

## Goals / Non-Goals

**Goals:**

- Keep AI request contracts provider-neutral and independent of concrete tools.
- Ensure explicit per-call tools are isolated for concurrent calls while preserving the public `bind_tools()` compatibility path without mutating its source client.
- Split transport code by responsibility without changing the canonical import path or wire behavior.
- Make malformed catalog inputs and schema conversion failures diagnosable offline.
- Retain `fake` as an intentional offline provider, not an implicit test-only dependency.

**Non-Goals:**

- Do not add providers, alter provider/model selection policy, or change request authentication.
- Do not move session, core, TUI, or tool execution code into this change.
- Do not change JSONL session persistence or model catalog file format.

## Decisions

### Normalize tool definitions at the composition boundary

Move concrete object introspection from `ai.model.ToolDefinition` into an application-composition adapter that returns a validated `ToolDefinition`. Fail conversion with a domain-specific diagnostic containing the tool name and root exception. AI types keep value-object serialization only.

This follows the existing composition-root dependency direction and avoids importing `tools`. Keeping a permissive `Any` helper in AI would avoid call-site edits but would preserve the blurred boundary and silent fallback.

### Make tool state immutable and request-scoped

`generate(messages, tools=...)` and `stream(messages, tools=...)` will serialize only their argument. A compatibility `bind_tools()` call will return an independent lightweight bound-client view, rather than altering the reusable transport instance; the view delegates requests with its captured immutable definitions.

Removing `bind_tools()` outright would simplify the protocol but would unnecessarily break callers using the public AI contract. Keeping mutable state would leave the concurrency defect unresolved.

### Split the OpenAI-compatible transport by collaboration boundary

Keep `OpenAICompatClient` as the public facade. Extract pure request-schema/response-conversion helpers and the SSE stream/retry driver into focused modules, each below the repository size guidance. Shared HTTP-client ownership and `aclose()` remain with the facade so connection reuse and shutdown semantics stay centralized.

### Preserve catalog resilience while exposing diagnostics

Continue loading valid records when a user catalog has invalid entries. Each skipped provider or model record logs a warning with path and contextual location; JSON/read failures retain their current warning-and-empty-overlay behavior. This is preferable to failing application startup because `models.json` is explicitly user-editable.

## Risks / Trade-offs

- [Bound-client compatibility view changes identity semantics] → Document that `bind_tools()` returns an isolated view and add tests for both old calling form and explicit per-call tools.
- [Transport extraction changes streaming edge cases] → Preserve existing SSE regression fixtures and test request JSON plus retry behavior before and after extraction.
- [More catalog warnings can be noisy] → Emit one concise warning per invalid entry with no secrets or raw credential data.
- [Composition adapter becomes the tool schema boundary] → Keep it small, typed, and covered by import-boundary tests so it does not become a second tool registry.

## Migration Plan

1. Add regression tests that demonstrate the current mutable-tool contamination risk and expected diagnostics.
2. Introduce normalized conversion and request-scoped tool handling behind existing public imports.
3. Extract transport helpers, migrate internal callers to explicit per-call tools, and retain the bound-client compatibility view.
4. Add catalog diagnostics and run focused AI/boundary tests, followed by the repository fast quality suite.
5. Roll back by restoring the facade's prior helper delegation if a provider wire-compatibility regression appears; no persisted data migration is needed.

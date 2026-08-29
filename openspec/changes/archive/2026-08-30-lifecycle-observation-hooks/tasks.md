## 1. Core Hook Contract

- [x] 1.1 Add red unit tests for lifecycle Hook scopes, phases, detached event snapshots, registration order, and ignored return values.
- [x] 1.2 Implement the provider-neutral `LifecycleHookEvent`/Hook contract, event classification, public exports, and `AgentLoopConfig.lifecycle_hooks` injection.
- [x] 1.3 Connect configured Hooks to Agent events while preserving existing listener ordering, async draining, cancellation, and run correlation.

## 2. Model and Session Lifecycle

- [x] 2.1 Add regression tests for exactly-once model request start/finish events on success, failure, and cancellation.
- [x] 2.2 Emit explicit model request boundary events and classify model stream, budget, and usage events as model updates.
- [x] 2.3 Add session-scope Hook tests and invoke session lifecycle observations with session/run correlation without changing EventBus subscribers.

## 3. Composition and Compatibility

- [x] 3.1 Expose Hook injection through AgentSession, SessionManager, and app composition factories while preserving session switching and existing callers.
- [x] 3.2 Add contract/import-boundary tests proving concrete provider, tool, MCP, Skill, and UI implementations are not imported by core Hook code.
- [x] 3.3 Update v0.4 iteration, architecture, testing documentation, and run focused, layered, lint, OpenSpec, and build verification.

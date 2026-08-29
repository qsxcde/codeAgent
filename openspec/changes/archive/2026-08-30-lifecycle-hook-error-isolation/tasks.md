## 1. Hook diagnostic contract

- [x] 1.1 Add red unit tests for structured sync/async Hook diagnostics, stable identity, correlation fields, and ignored `CancelledError`.
- [x] 1.2 Implement immutable `HookDiagnostic`, safe Hook identity, metadata conversion, and public core exports.

## 2. Core isolation

- [x] 2.1 Protect core lifecycle snapshot construction and record snapshot-stage diagnostics without stopping Agent events.
- [x] 2.2 Record synchronous invocation and asynchronous await failures while preserving Hook order, listener compatibility, and task cancellation/draining.
- [x] 2.3 Add core regression coverage proving a failing Hook cannot fail or alter a completed/failed/cancelled Agent run.

## 3. Session isolation and visibility

- [x] 3.1 Add session-side structured diagnostics for sync, async, and snapshot failures while retaining `lifecycle_hook_errors` compatibility.
- [x] 3.2 Transfer core Agent diagnostics through SessionRuntime and expose the combined diagnostics from AgentSession.
- [x] 3.3 Add session regression coverage for committed persistence, cancellation cleanup, core/session correlation, and non-persistence of diagnostics.

## 4. Documentation and verification

- [x] 4.1 Update lifecycle-hook spec, architecture/testing docs, README or iteration notes, and mark V4-29 complete.
- [x] 4.2 Run focused tests, unit/contract and full tests, Ruff, scale scan, diff check, OpenSpec validation, and build; review the final diff for unrelated changes.

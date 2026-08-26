## 1. Baseline and boundaries

- [x] 1.1 Inventory current session imports, public exports, compatibility adapters and all application/test call sites before moving files.
- [x] 1.2 Freeze recovery, append-only, parent-link, fork, compaction, usage, event, confirmation and rollback behavior as migration acceptance cases.
- [x] 1.3 Create the target package skeleton for `runtime/`, `events/`, `persistence/`, `compaction/` and `navigation/` without changing public imports.
- [x] 1.4 Document and test the dependency direction: session subpackages may depend on core message/event contracts, but not on `ai`, `tools` or `config`.

## 2. Extract session runtime responsibilities

- [x] 2.1 Move `SessionRuntime` execution state and core Agent invocation into `runtime/controller.py`, preserving run identifiers, recursion limits, tool timeouts and transform-context behavior.
- [x] 2.2 Extract confirmation request creation, response waiting, cancellation and cleanup into `runtime/confirmation.py` without changing approval event payloads or sequential-wait semantics.
- [x] 2.3 Extract core-to-session event mapping and side-effect observation into `runtime/event_mapper.py`, preserving event types, metadata and lifecycle order.
- [x] 2.4 Extract HTTP/provider error presentation into `runtime/error_policy.py`, preserving existing user-facing messages and exception fallback behavior.
- [x] 2.5 Make `AgentSession` delegate runtime operations while retaining its public methods, history ownership, summary state and rollback semantics.
- [x] 2.6 Introduce the smallest injectable Agent runner boundary needed by session runtime, with the existing core Agent as the first adapter and no new external dependency.
- [x] 2.7 Add regression tests for concurrent-run protection, abort/steer, confirmation cancellation, retryability and event ordering.

## 3. Reorganize events, compaction and navigation

- [x] 3.1 Move `EventBus` into `events/bus.py` and update session exports/callers without changing subscriber isolation or unsubscribe behavior.
- [x] 3.2 Split compaction estimation/cut-point logic and file-operation details into `compaction/policy.py` and `compaction/details.py`, retaining full-turn boundaries and summary semantics.
- [x] 3.3 Move summary service coordination only where needed, keeping summarizer injection outside session and avoiding provider-specific imports.
- [x] 3.4 Move `tree.py` into `navigation/tree.py` and make it depend directly on persistence session models rather than the storage façade.
- [x] 3.5 Add import-boundary and pure-function tests for event, compaction and tree modules.

## 4. Reorganize persistence

- [x] 4.1 Create `persistence/protocol.py` and `persistence/models.py`, migrating `SessionStore`, `SessionRef`, `UsageStats`, `CompactionEntry` and `CompactionState` while preserving the protocol contract.
- [x] 4.2 Define the internal record types for session headers, messages, metadata, usage, model changes and compaction entries in `persistence/records.py`.
- [x] 4.3 Move JSONL serialization, message conversion, header/version validation and malformed-line handling into `persistence/codec.py`.
- [x] 4.4 Move `JsonFileStore` into `persistence/jsonl_store.py`, keeping append-only writes, streaming reads, fork behavior, permissions and failure isolation unchanged.
- [x] 4.5 Move `MemoryStore` into `persistence/memory_store.py` and align its observable behavior with the file backend through shared protocol tests.
- [x] 4.6 Move metadata indexing into `persistence/index.py` and path/process locking helpers into `persistence/locking.py` without changing index invalidation or rebuild behavior.
- [x] 4.7 Move successful-turn, usage and compaction commit coordination into `persistence/commit.py`; failed and cancelled turns must remain uncommitted.
- [x] 4.8 Preserve `codeagent.session.store` as an export façade while migrating all internal imports to the new persistence modules.
- [x] 4.9 Add dual-backend tests for recovery, corrupted lines, unknown entries, metadata, usage, compaction, fork, index rebuild and append concurrency.

## 5. Migrate callers and remove obsolete internals

- [x] 5.1 Update `app/composition`, CLI, TUI and session tests to use the new internal module paths while retaining stable public façade imports.
- [x] 5.2 Verify the eight built-in tool/session integration paths remain unchanged and no session module imports `ai`, `tools` or `config`.
- [x] 5.3 Remove duplicate implementations and obsolete private compatibility adapters after all call sites are migrated.
- [x] 5.4 Verify no import cycles exist among `session`, `runtime`, `events`, `persistence`, `compaction` and `navigation`.
- [x] 5.5 Review whether `store.py` and other façades still have declared consumers; retain only intentional public exports and document any remaining compatibility path.

## 6. Focused verification and handoff

- [x] 6.1 Run the focused session, persistence, compaction, tree, manager and container/policy regression tests.
- [x] 6.2 Run syntax/import-boundary checks and verify the target directory tree matches the design.
- [x] 6.3 Run `openspec validate --specs` and inspect the final diff for JSONL format, event sequence or public import regressions.
- [x] 6.4 Record focused test results and hand off full-suite execution to the user; do not claim full-suite status without user-provided output.

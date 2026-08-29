## 1. Archive-aware query and persistence

- [x] 1.1 Extend `SessionRef`/`SessionQuery` with archive state and compatibility defaults; add value-object and old-index tests.
- [x] 1.2 Implement archive/unarchive metadata for MemoryStore and JsonFileStore, including index rebuild/restart and default/explicit archive queries.
- [x] 1.3 Implement validated single/batch delete store boundaries with symlink/path protection, companion-index cleanup and failure diagnostics.

## 2. Session manager safety

- [x] 2.1 Add manager archive/unarchive/delete-many operations with all-target preflight, current/running protection and resident registry cleanup.
- [x] 2.2 Verify archive/delete operations do not alter messages, compaction, parent relationships or unrelated sessions, including partial failure behavior.

## 3. TUI session management

- [x] 3.1 Add archived listing plus archive/unarchive/delete command parsing and typed confirmation feedback.
- [x] 3.2 Cover batch commands, missing/invalid/protected targets, partial failures, empty states, no model requests and existing sessions/search/filter compatibility.

## 4. Documentation and acceptance

- [x] 4.1 Update sessions/TUI main specs, v0.4 status, README, testing guide and architecture notes.
- [x] 4.2 Run focused tests, unit/contract, full tests, Ruff, scale scan, OpenSpec validation, diff checks and build checks.

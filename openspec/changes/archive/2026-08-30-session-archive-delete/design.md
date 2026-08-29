## Context

See `proposal.md` and the existing `sessions`/`tui` specifications. V4-24 already provides indexed metadata queries and resident runtime status, while JSONL remains the source of truth and `SessionRef` is the stable list boundary.

## Goals / Non-Goals

**Goals:**

- Persist a reversible archive flag without rewriting conversation history.
- Make default listing safe and useful while retaining an explicit archived view.
- Provide deletion through a narrow, validated store boundary with confirmation and resident-session protection.
- Keep MemoryStore and JsonFileStore behavior equivalent and keep TUI operations offline/readable.

**Non-Goals:**

- No trash/recycle-bin retention, undelete after physical deletion, export, cross-session bulk query language, or background cleanup job.
- No deletion of the whole sessions directory, arbitrary paths, or currently active session shells.
- No historical run-status persistence; archive state is metadata, not runtime outcome.

## Decisions

1. **Archive state is append-only metadata.** `archive(session_id, archived)` writes the existing JSONL `meta` entry shape and updates the derived index. This preserves old messages and makes restart behavior deterministic. MemoryStore stores the same fact in its metadata map.

2. **Query range is explicit.** Extend `SessionQuery` with `archived: bool | None`, where `False` is the default active-only view, `True` is the archived-only view, and `None` includes both. Existing callers remain active-only after archiving, while administrative views can opt in.

3. **Delete is a store operation, not a generic filesystem helper.** JsonFileStore validates a non-empty single-component session id, rejects symlink targets, verifies the target path is directly under its configured directory, removes the index first and then the JSONL file under the session lock. If JSONL removal fails, the missing index is safely rebuilt later; unrelated files are never addressed. MemoryStore removes only maps belonging to the id.

4. **Manager performs preflight and resident protection.** `SessionManager.delete_many(ids, confirmed=True)` deduplicates ids, checks that every target exists, rejects the current id and any resident session whose runtime is active, then executes store deletion. Failed deletions are returned as per-id diagnostics; the manager removes successfully deleted idle shells from its registry. Archive/unarchive has the same target existence checks but does not delete data.

5. **TUI uses a typed confirmation token.** The literal final token `confirm` is required for delete commands, which is deterministic for both the line-oriented backend and Textual UI. Archive/unarchive are reversible and do not require confirmation. `/sessions archived` is the explicit read-only archived view; ordinary list/search/filter continues to use the active-only query range.

6. **Failures remain visible.** Store and manager methods raise focused `ValueError`/`OSError` errors; TUI catches them and renders success/failure counts and target ids. No command falls through to ordinary conversation submission.

## Risks / Trade-offs

- [Risk] Removing two files is not one filesystem transaction → remove the derived index first, preserve JSONL on failure, and make the next read rebuild the index.
- [Risk] A user may archive the current session and then not see it in the default list → keep the current session usable, provide `/sessions archived`, and report the explicit state change.
- [Risk] Typed confirmation is less discoverable than a modal → include exact command usage in the refusal; it is stable across headless and Textual test backends.
- [Risk] Old indexes lack the archive field → invalidate them through existing semantic validation and rebuild from JSONL, treating absent archive metadata as false.

## Migration Plan

No data migration is required. Existing JSONL files and indexes remain readable; the first read rebuilds an old index with `archived=false`. Rolling back code leaves archive meta entries harmless to older readers, while physically deleted sessions cannot be restored without external backups.

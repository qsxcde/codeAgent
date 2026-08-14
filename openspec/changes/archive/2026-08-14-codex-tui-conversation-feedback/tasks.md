## 1. Conversation Rendering

- [x] 1.1 Add semantic theme tags and render full-width user blocks, compact assistant bullets, and transient activity blocks through the pure TUI components.
- [x] 1.2 Add Codex-style tool summaries and bounded expandable intent-diff rendering for edit and write calls.
- [x] 1.3 Extend component and transcript tests for spacing, style tags, hidden reasoning, summaries, diffs, and click mapping.

## 2. Event Identity And Activity Lifecycle

- [x] 2.1 Preserve tool call ID and tool metadata when session events translate tool results, with tests for concurrent out-of-order results.
- [x] 2.2 Update the TUI view model to track activity visibility and attach results by call ID with FIFO compatibility fallback.
- [x] 2.3 Add an activity-frame scheduler in the Textual app that redraws only while active and stops on terminal states or exit.

## 3. Verification And Documentation

- [x] 3.1 Update Textual backend tests and perform a headless visual/interaction check of conversation, tool expansion, and activity rendering.
- [x] 3.2 Update the user-facing TUI documentation and main TUI specification for the new message, feedback, and status-bar behavior.
- [x] 3.3 Run focused and full feasible test suites, validate the OpenSpec change, and record completion in this checklist.

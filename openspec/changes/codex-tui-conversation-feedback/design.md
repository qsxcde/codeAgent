## Context

See proposal.md for motivation and `specs/tui/spec.md` for the behavior contract. The current TUI already separates pure `RichLine` components from the Textual backend, supports click-to-expand tools, and receives `TOOL_CALL` before `TOOL_RESULT`. Tool results currently lose their call ID and `TuiModel` assigns them FIFO, which is incorrect for concurrent calls. Reasoning deltas are accumulated and rendered verbatim.

## Goals / Non-Goals

**Goals:**

- Keep all message rendering engine-independent and assertable through style tags.
- Make user, assistant, activity, and tool records compact and visually scanable.
- Render actual edit/write intent as a concise, expandable diff without rereading modified files.
- Preserve event-driven model and tool execution while adding bounded UI-only animation.
- Correctly associate concurrent tool results with their initiating call.

**Non-Goals:**

- Markdown parsing, syntax highlighting, or a general code review UI.
- Changing tool execution order, tool schemas, model prompts, or headless CLI output.
- Persisting activity frames or thought text in session history.
- Adding a configuration surface for animation cadence or theme selection.

## Decisions

### D1. Render conversation blocks through the existing RichLine model

`UserBlock` will wrap text to the transcript width and pad every line with a `user_bg` background span. Its first line starts with a muted `›`. `AssistantBlock` will render only the assistant body: the first line has a muted `• ` prefix and continuation lines reserve the same indentation. Raw reasoning text remains accumulated only as transient session state and is not emitted by `render()`.

`Transcript` will insert one unmapped blank `RichLine` between persistent top-level blocks. The existing line-to-block map will include `None` for gap and activity lines so tool clicks remain accurate.

Alternative: create Textual widgets for each message. Rejected because it would duplicate wrapping, scrolling, click mapping, and style behavior outside the pure component layer.

### D2. Model waiting as a transient ActivityBlock

`TuiModel` owns one transient `ActivityBlock` outside `Transcript.blocks`. It renders a short `• 思考中` label whose dot/frame changes independently of message content. A session start activates it; a tool call deactivates it; the final tool result reactivates it until a new tool call, assistant text, terminal event, or error changes state.

`TuiApp` owns a single asyncio task while activity is visible. It advances the frame at 0.45 seconds and schedules a normal render. The task does not poll a model, session, or tool; it is cancelled on every terminal state and app exit.

Alternative: make Textual own the timer. Rejected because activity state belongs in the engine-independent view model and must be testable without Textual.

### D3. Use structured tool-call intent for Codex-style summaries and diffs

`ToolCallBlock` retains its original call ID, name, and args. A formatter produces a verb-specific summary, for example `Edited path (+2 -2)` or `Ran command (exit 0 · 0.2s)`. For `edit`, compare `old_string` and `new_string` with `difflib.SequenceMatcher`; for `write`, represent the supplied content as additions. Expanded details use `RichLine` spans for line number, deletion, addition, and context backgrounds. Other tools retain their full textual result when expanded.

This is intentionally an intent diff, not a disk diff: it avoids rereading files and remains safe when another process edits a file after the tool call. The completion state still reflects the real tool result.

### D4. Preserve tool result identity through AgentEvent metadata

When translating a `ToolMessage`, `AgentSession` will include `tool_call_id` and tool name in `AgentEvent.metadata`. `TuiModel` stores pending tool blocks by ID and updates the matching block. Events lacking an ID retain a FIFO fallback for backwards-compatible tests and alternate event producers.

Alternative: serialize tool execution. Rejected because execution is intentionally parallel and serialization would degrade agent throughput.

### D5. Extend the semantic theme instead of embedding terminal colors

Theme adds controlled tags for user background/prompt, assistant prompt, activity frame, and diff add/remove/context backgrounds. Components emit tags only; `textual_backend` continues mapping them to Rich styles. This retains true-color fallback behavior and keeps component tests independent of ANSI codes.

## Risks / Trade-offs

- [Intent diff differs from final file contents] -> Label it through the operation summary and use it only after successful tool completion; do not claim it is a repository diff.
- [Animation can cause needless redraws] -> Run only while activity is visible, use a 0.45-second cadence, and cancel the task deterministically.
- [Concurrent result metadata may be absent from external event producers] -> Keep FIFO fallback and test both paths.
- [Full-width user backgrounds amplify wide-terminal whitespace] -> Limit the behavior to user messages, preserve a single line of inter-block spacing, and use a low-contrast fill.
- [Long edit args produce very large diffs] -> Cap displayed diff lines and append a muted truncation marker while retaining the existing tool result on expansion.

## Migration Plan

1. Add theme tags and pure component tests for conversation blocks, activity frames, summaries, and diffs.
2. Propagate tool call IDs and replace FIFO assignment with ID lookup plus fallback.
3. Wire activity lifecycle and bounded animation task through `TuiApp`.
4. Update the Textual snapshot/interaction tests and main TUI documentation.
5. Validate with the full test suite and manual TUI checks for one normal reply, one edit, concurrent tools, cancellation, and a narrow terminal.

Rollback is a normal git revert; no stored data or external API contract changes are involved.

## 1. Establish the AI request boundary

- [x] 1.1 Add a typed composition-layer adapter that converts concrete tool objects into validated `ToolDefinition` values and reports conversion failures with tool context.
- [x] 1.2 Remove concrete-tool introspection and silent schema-conversion fallback from `codeagent.ai.model`; retain only provider-neutral value-object serialization there.
- [x] 1.3 Update the AI import-boundary tests to assert that concrete tool schema adaptation remains outside `src/codeagent/ai`.

## 2. Isolate provider requests and split transport responsibilities

- [x] 2.1 Add regression tests proving that concurrent `generate` and `stream` calls with different tools produce isolated request payloads.
- [x] 2.2 Change `OpenAICompatClient` to construct requests from per-call normalized tool definitions, without mutable tool state on the shared transport client.
- [x] 2.3 Preserve `bind_tools()` compatibility by returning an independent bound-client view and add tests that it cannot alter the source client's requests.
- [x] 2.4 Extract request serialization/response assembly and streaming retry/framing helpers into focused transport modules while preserving the `OpenAICompatClient` public import path and existing SSE behavior.
- [x] 2.5 Add or update type annotations so public AI catalog and transport interfaces do not expose unparameterized container types where a concrete shape is known.

## 3. Make user catalog recovery diagnosable

- [x] 3.1 Emit contextual warnings for every skipped malformed provider or model record in `models.json`, without logging secrets or preventing valid entries from loading.
- [x] 3.2 Add catalog tests for invalid provider shapes, invalid model records, mixed valid/invalid inputs, and unreadable or malformed catalog files.

## 4. Validate the refactor

- [x] 4.1 Run focused AI model, catalog, provider, transport, and import-boundary tests offline.
- [x] 4.2 Run `uv run pytest -m "unit or contract" -q --strict-markers`, `uv run ruff check src tests scripts`, and `git diff --check`.
- [x] 4.3 Confirm all modified production AI modules meet the repository's file/function size guidance, and record any justified exception in the change documentation.

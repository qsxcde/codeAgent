## Why

The AI infrastructure layer has correct top-level dependency direction, but several internal boundaries still blur: it adapts concrete tool objects, retains request-specific tool state on reusable clients, and suppresses some malformed catalog and schema errors. Its main OpenAI-compatible transport also exceeds the repository's module and function-size guidance. Tightening these boundaries now prevents concurrent requests from contaminating one another and keeps AI adapters independently testable and maintainable.

## What Changes

- Define a provider-neutral AI request contract in which callers pass normalized tool definitions for each request; AI modules no longer introspect concrete tool `args_schema` objects.
- Make OpenAI-compatible client request construction request-scoped, so concurrently streamed or generated requests cannot reuse another request's tool definitions.
- Split transport responsibilities into cohesive modules while preserving the public `OpenAICompatClient` import path and protocol behavior.
- Make malformed user model-catalog entries and tool-schema conversion failures observable through structured diagnostics rather than silently discarding their cause.
- Keep the production AI package limited to production model infrastructure; retain the fake provider only as an explicitly supported offline provider and document that role.

## Capabilities

### New Capabilities

- `ai-provider-isolation`: Defines normalized AI request inputs, concurrent client isolation, and diagnostics for provider-facing catalog and schema boundaries.

### Modified Capabilities

- `ai-import-boundaries`: Clarifies the canonical AI contract boundary so concrete tool adaptation stays outside the AI package while public AI import paths remain stable.

## Impact

- Affects `src/codeagent/ai/model/`, `src/codeagent/ai/transport/`, and `src/codeagent/ai/catalog/`, plus the composition adapter that builds model-visible tool definitions.
- May remove or deprecate mutable `bind_tools()` behavior in favor of per-call `tools` parameters; existing public imports and provider selection remain compatible.
- Adds offline regression tests for concurrent requests, diagnostic output, canonical import boundaries, and transport behavior; no new dependencies or real network calls are required.

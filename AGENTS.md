# Repository Guidelines

## Project Structure & Module Organization

- `src/codeagent/app/` contains the composition root, CLI, and TUI; cross-layer wiring belongs in `app/container.py` or `app/main.py`.
- `src/codeagent/core/` is the dependency-light orchestration layer; `session/` owns state, JSONL persistence, compaction, and session trees; `ai/` contains providers and transports; `tools/` contains built-in and MCP tools.
- `src/codeagent/resources/` stores bundled prompts and skills. Tests live under `tests/`, generally mirroring source packages; `tests/conftest.py` provides isolated configuration and filesystem fixtures.
- `docs/` contains architecture and iteration notes. `openspec/` contains specifications and change artifacts.

## Build, Test, and Development Commands

```bash
uv sync --group dev                 # Install runtime and development dependencies
uv run codeagent --prompt "你好"     # Run the headless CLI
uv run codeagent --tui               # Run the interactive terminal UI
uv run pytest -q                    # Run the complete test suite
uv run pytest tests/session/test_store.py::test_create_and_header
uv build                            # Build distribution artifacts
openspec validate --specs           # Validate main OpenSpec specifications
```

## Coding Style & Naming Conventions

Use Python 3.12+, four-space indentation, type annotations, `snake_case` functions and variables, `PascalCase` classes, and uppercase constants. Match existing formatting; Black, Ruff, and mypy are not currently configured. Keep modules cohesive, avoid top-level side effects, and write comments for design reasons rather than line-by-line narration. Preserve the dependency direction: `core/` must not import `config`, `ai`, `tools`, or `session`; `session/` must not import `ai`, `tools`, or `config`.

## Testing Guidelines

Use pytest with behavior-focused names such as `test_load_context_reconstructs_summary_plus_kept`. Keep tests offline and platform-independent; use `tmp_path`, `monkeypatch`, and the `FakeClient` instead of real credentials or network calls. Add regression tests for bug fixes and run the narrow test first, then `uv run pytest -q`.

## Commit & Pull Request Guidelines

Use short imperative commits with the repository’s prefixes, for example `feat:`, `fix:`, `docs:`, `test:`, or `ci:`; Chinese descriptions are also present in history. PRs should explain the behavior change, list verification commands, and update relevant OpenSpec artifacts or docs. Include screenshots or terminal recordings for TUI changes. Keep unrelated worktree changes out of the PR.

## Security & Configuration Tips

Store credentials only in `~/.codeagent/.env`; the application intentionally does not read a repository-local `.env`. Never commit keys, generated secrets, or user session data. Use the `fake` provider for local development and tests.

## 1. Baseline and public contracts

- [x] 1.1 Inventory current imports and tests for `atomic/bash.py`, `tools/security.py` and `tools/mcp/config.py`, distinguishing public exports from private implementation imports.
- [x] 1.2 Freeze the existing Bash, security and MCP behavior cases as the migration acceptance baseline, including allow/ask/deny decisions, output formatting, timeout/cancel states and public import paths.
- [x] 1.3 Define the internal process request/result boundary and the dependency direction: atomic tools may call execution/security services, while execution and security must not import atomic tools, core, session or ai.
- [x] 1.4 Record the eight built-in atomic tools (`read`, `write`, `edit`, `grep`, `find`, `ls`, `bash`, `skill`) and distinguish them from `AtomicTool`, MCP adapters and tools-layer infrastructure.
- [x] 1.5 Create a cross-platform behavior matrix for path, encoding, newline, glob, traversal, hidden-entry, permission, symlink/junction and error semantics before moving implementations.

## 2. Extract Bash execution infrastructure

- [x] 2.1 Create `tools/execution/` with package exports and platform-neutral process request/result types without introducing third-party dependencies.
- [x] 2.2 Move Shell backend selection, Bash executable discovery, WSL shim filtering and restricted environment construction into `tools/execution/shell.py`, with no implicit WSL fallback.
- [x] 2.3 Move synchronous and asynchronous subprocess execution, stdout/stderr temporary-file capture, UTF-8 decoding, timeout handling, cancellation handling and process-tree cleanup into `tools/execution/process.py`.
- [x] 2.4 Implement the POSIX backend shared by Linux/macOS for `start_new_session`, process-group signals and deterministic cleanup.
- [x] 2.5 Implement the Windows Git Bash backend for process-group flags, `CREATE_NO_WINDOW`, `taskkill /T` and explicit cleanup uncertainty; keep WSL as an explicit future backend only.
- [x] 2.6 Ensure the shared process runner preserves `cleanup_confirmed` / `cleanup_uncertain` semantics and cleans temporary files on success, failure, timeout and cancellation.
- [x] 2.7 Update `BashTool._invoke` and `BashTool.ainvoke` to use the new execution services, retaining Bash-specific exit-code semantics, output truncation and user-facing result formatting.
- [x] 2.8 Remove duplicated subprocess, Shell discovery and process cleanup implementations from `atomic/bash.py` while retaining `BashTool`, `BashArgs`, `BashInvocationResult` and the intentional `DANGEROUS_PATTERNS` export.
- [x] 2.9 Add Bash backend tests for Linux/macOS POSIX behavior, Windows Git Bash resolution, WSL shim rejection, cwd/environment handling, timeout/cancellation and cleanup uncertainty.
- [x] 2.10 Run Bash execution tests for normal commands, output truncation, non-zero exits, process-tree cleanup and structured result metadata on the available host platform.

## 3. Extract and reorganize security responsibilities

- [x] 3.1 Convert `tools/security.py` into a `tools/security/` package with `decision.py`, `bash_rules.py`, `filesystem.py`, `mcp.py`, `classifier.py` and package exports.
- [x] 3.2 Move Bash dangerous patterns, Shell tokenization, logical-segment parsing, nested-shell/command-substitution detection and recursive `rm` intent analysis into `security/bash_rules.py`.
- [x] 3.3 Move `SecurityDecision` and action constants into `security/decision.py`, and move filesystem boundary checks and MCP permission classification into their dedicated modules.
- [x] 3.4 Rebuild `classify_bash` and `classify_tool` on the extracted modules, preserving deny/ask/allow precedence, injected rules, cwd handling, secret-path checks and MCP dispatch behavior.
- [x] 3.5 Re-export the existing public security names from `security/__init__.py`, update imports in the composition root and remove all imports from security code into `atomic/bash.py` private functions.
- [x] 3.6 Migrate security tests to stable classification/module boundaries, retaining coverage for dangerous command variants, file boundaries, MCP rules, custom policies and platform path behavior.
- [x] 3.7 Add or update import-boundary checks proving `security` and `execution` do not depend on atomic tools, core, session or ai.

## 4. Cross-platform atomic tool behavior

- [x] 4.1 Verify `read`, `write` and `edit` use injected `cwd`/`FsOps` consistently for Windows, Linux and macOS paths, including drive/UNC paths, permissions and missing targets.
- [x] 4.2 Verify `read`, `write` and `edit` preserve the documented UTF-8, binary preview, LF, CRLF and BOM behavior independently of host newline translation.
- [x] 4.3 Verify `grep`, `find` and `ls` use deterministic POSIX-style relative output, glob/path-separator semantics, sorting, result limits and noise-directory pruning across platforms.
- [x] 4.4 Cover Unix symlink and Windows junction/reparse-point traversal behavior, including loops and workspace-boundary cases, without changing the existing default traversal policy.
- [x] 4.5 Verify `skill` remains platform-independent by resolving only the injected in-memory registry and performing no filesystem or subprocess work.
- [x] 4.6 Keep `McpTool` classified as an external adapter and test that MCP server command, stdio, environment and configuration paths are isolated from built-in atomic tool semantics.

## 5. Split MCP configuration responsibilities

- [x] 5.1 Create `mcp/server_config.py` for `McpServerSpec` and `parse_mcp_config`, preserving diagnostics and malformed-entry handling.
- [x] 5.2 Create `mcp/permissions.py` for `McpPermissionRules` and `parse_mcp_permissions`, preserving normalization, wildcard matching and deny/ask/allow precedence.
- [x] 5.3 Reduce `mcp/config.py` to a deliberate public export surface, update loader and policy composition imports, and keep existing `codeagent.tools.mcp.config` public imports working.
- [x] 5.4 Run MCP configuration, permission, loader and adapter tests to verify server startup behavior, permission matching, tool naming, cleanup behavior and platform-specific command/env handling remain unchanged.

## 6. Final integration and verification

- [x] 6.1 Verify `tools/atomic/bash.py` contains only Bash tool schema, orchestration, result mapping and Bash-specific formatting, with no process-platform or security parser implementation left behind.
- [x] 6.2 Verify `tools/security/`, `tools/execution/` and `tools/mcp/` dependencies are one-directional and do not introduce import cycles.
- [x] 6.3 Verify the eight built-in tools are the only built-in atomic tool set and MCP adapters remain an extension path.
- [x] 6.4 Run the focused tools, cross-platform contract and MCP test suites plus existing container/policy regression tests.
- [x] 6.5 Run `openspec validate --specs` and inspect the final diff for accidental behavior changes or unrelated file edits.
- [x] 6.6 After focused verification passes, hand off full-suite execution to the user for final confirmation.

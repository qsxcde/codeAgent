## 1. Error contract

- [x] 1.1 Add the stable Provider error types, classification rules, bounded detail extraction, redaction, and retry metadata.
- [x] 1.2 Export the public error contract and add unit coverage for HTTP, transport, timeout, authentication, rate-limit, and unsupported-parameter cases.

## 2. Transport integration

- [x] 2.1 Pass Provider identifiers from built-in factories into the OpenAI-compatible client.
- [x] 2.2 Classify final failures in non-streaming and streaming requests while preserving HTTP status exception compatibility.
- [x] 2.3 Add regression coverage proving equivalent streaming and non-streaming failures expose the same error contract.

## 3. Verification and documentation

- [x] 3.1 Update architecture, testing, and v0.4 iteration documentation with the new error contract and verification baseline.
- [x] 3.2 Run focused tests, unit/contract tests, full offline tests, Ruff, scale scan, diff checks, build, and OpenSpec validation; mark this change complete.

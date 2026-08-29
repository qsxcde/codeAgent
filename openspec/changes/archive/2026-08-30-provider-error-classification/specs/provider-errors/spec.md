## Purpose

为模型调用提供一致、可诊断且不泄露敏感信息的 Provider 错误语义，使上层能够区分用户配置问题、临时服务故障和可重试的传输失败。

## ADDED Requirements

### Requirement: Provider failures have stable classifications

The system SHALL classify Provider call failures into stable categories for network failures, timeouts, rate limits, authentication failures, invalid requests, unsupported parameters, server failures, and unknown failures.

#### Scenario: Rate limit response exposes retry metadata

- **WHEN** a Provider responds with HTTP 429 and optionally supplies `Retry-After` or a request ID
- **THEN** the raised error is classified as a rate limit, marked retryable, and exposes the status code plus any safely parsed retry delay and request ID

#### Scenario: Authentication failure is not retryable by classification

- **WHEN** a Provider responds with HTTP 401 or 403
- **THEN** the raised error is classified as an authentication failure and is not marked retryable

#### Scenario: Unsupported parameter is distinguished from a generic bad request

- **WHEN** a Provider responds with HTTP 400 or 422 and its bounded error detail explicitly indicates an unsupported or unknown parameter
- **THEN** the raised error is classified as an unsupported parameter and retains the bounded diagnostic detail

#### Scenario: Network and timeout failures are retryable

- **WHEN** the transport raises a connection-related error or a timeout before a complete response is received
- **THEN** the raised error is classified as network or timeout respectively and is marked retryable

#### Scenario: Server failure is retryable

- **WHEN** a Provider responds with HTTP 5xx
- **THEN** the raised error is classified as a server failure and is marked retryable

### Requirement: Provider errors carry safe diagnostic context

The system SHALL attach the Provider identifier, model identifier, HTTP status when available, and a bounded sanitized detail to classified errors without exposing API keys, authorization values, passwords, or tokens.

#### Scenario: Diagnostic context identifies the model request

- **WHEN** a configured Provider request fails
- **THEN** the error exposes the Provider and model identifiers supplied by the transport factory, together with available status and request metadata

#### Scenario: Sensitive response fields are redacted

- **WHEN** an error response contains fields commonly used for credentials or bearer tokens
- **THEN** the stored detail is length-bounded and masks those values

### Requirement: Streaming and non-streaming transport use the same error contract

The system SHALL raise the same classified Provider error contract for equivalent failures from streaming and non-streaming OpenAI-compatible requests, while HTTP classified errors remain compatible with `httpx.HTTPStatusError` consumers.

#### Scenario: Non-streaming HTTP failure is classified

- **WHEN** a non-streaming OpenAI-compatible request receives a non-success HTTP response after retries are exhausted
- **THEN** it raises a classified Provider error containing the response details

#### Scenario: Streaming HTTP failure is classified

- **WHEN** a streaming OpenAI-compatible request receives an equivalent non-success HTTP response before yielding an event
- **THEN** it raises the same classification and metadata contract as the non-streaming path

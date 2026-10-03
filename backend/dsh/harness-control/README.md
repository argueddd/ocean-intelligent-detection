# Harness cancellation bridge

This local bundle injects the installed SDK's `agents` and `jobs` services. It listens only on `127.0.0.1`, using `HARNESS_CONTROL_PORT` and the non-empty random `HARNESS_CONTROL_TOKEN` supplied by the backend environment. Tokens must not be written into tracked configuration or exposed to the browser.

`POST /cancel`, `Authorization: Bearer <token>`, JSON `{ "sessionId": "attached-session-id" }` cancels the exact live Agent, its runtime-owned descendants, and each member's session-owned background jobs. It uses `Agent.cancel({ kind: 'user' }, { keepInbox: true })`, `Agent.whenIdle()`, and the public job `list`/`kill`/`wait` APIs. Unowned jobs and other session trees are excluded. The bridge does not dispose Agents or close the shared Harness runtime.

A 200 response has `status: cancelled | idle`, `agentStatus: idle`, `cancelledSessionIds`, and `cancelledJobIds`. Success follows actual driver and producer quiescence; the SDK publishes its own ordinary idle events. Missing sessions return 404, invalid requests 400, invalid authentication 401, and cancellation that does not settle within `timeoutMs` returns 504. The default deadline is 30 seconds, with a configurable upper limit of 60 seconds. Concurrent cancellation requests for the same exact live Agent share one operation. Plugin disposal closes its listener and ends pending HTTP waits.

Offline contracts: `/opt/homebrew/bin/node --test backend/dev/contract-control.mjs`. They load real Cordis, AgentLoop, AgentRegistry, jobs, Bash, sandbox and subprocess implementations. Their in-process model adapter emits deterministic test chunks and makes no network or paid model requests.

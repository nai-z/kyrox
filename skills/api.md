---
name: api
description: API design and integration — REST, FastAPI, auth, security
triggers: api, endpoint, rest, http, fetch, request, response, fastapi, express, flask, route, webhook, auth, token, oauth, rate limit, cors, backend, serveur, server
---

# API Design & Integration

## Consuming APIs

- Handle every failure mode: network error, non-2xx status, malformed JSON, rate limits
- Show loading state before the request, clear it in `finally:`
- Abort stale requests (`AbortController` in JS, `.aclose()` in httpx)
- Cache responses when data doesn't change often

## Building APIs (FastAPI / Express)

- Validate all input at the boundary — never trust incoming data
- Return consistent shapes: `{"ok": true, "data": {}}` or `{"ok": false, "error": "msg"}`
- HTTP status codes that mean something:
  - `200` OK, `201` Created, `400` Bad input, `401` Unauthorized
  - `404` Not found, `429` Rate limit, `500` Server error
- Log errors server-side with enough context to debug
- Rate limit all public endpoints

## Authentication

- Never log tokens, passwords, or API keys — not even in debug mode
- Validate tokens on every protected request, not just login
- Short expiry on access tokens, refresh token pattern for long sessions

## Security

- Sanitize any user input that touches the filesystem or database
- CORS: explicit `allowed_origins` — never `*` in production
- Never expose stack traces or internal paths to the client

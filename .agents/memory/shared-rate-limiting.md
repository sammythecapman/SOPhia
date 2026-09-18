---
name: Shared rate limiting
description: Rate-limit state must be shared across production workers.
---

Production rate-limit state should live in a shared durable store rather than only in
process memory when the service runs multiple workers or autoscale instances.

**Why:** A process-local counter lets callers multiply the configured budget by the number
of workers and resets whenever a worker restarts.

**How to apply:** Use a database or managed rate-limit service, key by authenticated user
when available and by client IP otherwise, and keep the regression runner below the limit.
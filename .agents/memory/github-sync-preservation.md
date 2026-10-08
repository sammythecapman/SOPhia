---
name: GitHub sync preservation
description: User constraint on changes to SOPhia and its development environment.
---

Preserve the ability to successfully sync changes with GitHub.

**Why:** The user made this a condition of authorization to complete the task and improve SOPhia.

**How to apply:** Do not disrupt the Git connection, remote configuration, or authentication while changing the application or deployment. Broad authorization does not replace required confirmation for specific destructive actions or user-initiated publishing.

Use `git --no-optional-locks` for routine read-only status and diff checks.

**Why:** An ordinary diff check attempted an index lock and hit the workspace Git safeguard. Disabling optional locks let verification complete without bypassing the safeguard or changing Git settings.

**How to apply:** Do not use a dangerous Git allowance merely to inspect changes. Keep optional read-only checks separate from actual GitHub pushes, which were not exercised by those checks.
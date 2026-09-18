---
name: Replit production data publish
description: Replit managed Publish can apply schema without copying development rows unless the explicit production-data copy option is selected.
---

For this managed PostgreSQL setup, use the Publish UI option to copy the development database to production when the application depends on seeded data. A successful schema publish does not by itself guarantee that development rows are present in production.

**Why:** The service's startup validation correctly failed when production had the new tables but no corpus rows; selecting the explicit copy option populated the corpus and allowed the deployment to become healthy.

**How to apply:** Before publishing a data-dependent release, verify whether production should be replaced with development data and select the copy/overwrite option when appropriate. Treat the action as destructive to existing production data.
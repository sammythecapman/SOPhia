---
name: SOP answer provider
description: Provider constraint for the SOP query answer-generation path
---

The current Anthropic credential may be rejected unless the request includes an Anthropic workspace ID. The SOP query path therefore uses the already-working OpenAI credential for both embeddings and grounded answer generation unless a workspace-scoped Anthropic configuration is intentionally added.

**Why:** The unscoped Anthropic key returned a 400 before answer generation, while OpenAI chat completions succeeded with the existing project configuration.

**How to apply:** Preserve the structured JSON response contract and server-side exact-quote validation when changing the answer provider.
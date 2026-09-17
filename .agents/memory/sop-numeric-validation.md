---
name: SOP numeric validation
description: Deterministic validation rules for percentages, money suffixes, and computed amounts in grounded SOP answers.
---

Numeric validation must parse both symbol and word percentages, normalize money suffixes such as MM and M, and recognize explicit multiplication expressions such as “10% × $1,450,000.” Numeric claims may use facts from the user prompt plus the cited rule evidence; unsupported computed results must still be suppressed.

**Why:** Word-form percentages and parenthetical calculations initially looked numeric but were missed by the parser, causing valid threshold and injection conclusions to be withheld.

**How to apply:** Keep parsing and arithmetic checks deterministic and run regression cases for threshold ownership, seller-note terms, and startup injection computations whenever the answer schema changes.
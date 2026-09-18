---
name: Psycopg SQL literals
description: A psycopg-specific constraint for percent signs in SQL literals.
---

Parameterized psycopg queries must write literal percent signs as `%%`, including inside
`ILIKE` string literals; otherwise psycopg interprets `%S`, `%E`, or similar sequences as
invalid placeholders before PostgreSQL receives the query.

**Why:** Retrieval queries can work in direct SQL clients but fail at runtime only after
psycopg parses the parameterized statement.

**How to apply:** When adding or reviewing a parameterized query, search its SQL string for
literal `%` characters and double each one; leave `%s` parameter placeholders unchanged.
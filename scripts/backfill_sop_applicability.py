#!/usr/bin/env python3
"""Backfill structured applicability metadata for already-ingested SOP chunks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "artifacts" / "api-server"))
from applicability import classify_text  # noqa: E402
from db import connection  # noqa: E402


def main() -> None:
    updated = 0
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, section_ref, chunk_text FROM sop_chunks ORDER BY id"
        ).fetchall()
        with conn.transaction():
            for chunk_id, section_ref, chunk_text in rows:
                tags = classify_text(chunk_text, section_ref)
                conn.execute(
                    """
                    UPDATE sop_chunks
                    SET transaction_types = %s,
                        entity_structures = %s,
                        party_roles = %s,
                        program_scopes = %s,
                        product_lines = %s,
                        loan_size_bands = %s
                    WHERE id = %s
                    """,
                    (
                        tags["transaction_types"],
                        tags["entity_structures"],
                        tags["party_roles"],
                        tags["program_scopes"],
                        tags["product_lines"],
                        tags["loan_size_bands"],
                        chunk_id,
                    ),
                )
                updated += 1
    print(f"Backfilled applicability metadata for {updated} chunks.")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""Audit ESOP transaction tags against each chunk's own text and nearest heading."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "artifacts" / "api-server"))
from db import connection  # noqa: E402
import re


def main() -> None:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id, section_ref, chunk_text, transaction_types
            FROM sop_chunks
            WHERE 'esop' = ANY(transaction_types)
            ORDER BY id
            """
        ).fetchall()

    print(f"Auditing {len(rows)} chunks tagged with transaction type esop.")
    unjustified = 0
    for chunk_id, section_ref, chunk_text, stored_tags in rows:
        nearest_heading = section_ref.split(" > ")[-1]
        justified = bool(
            re.search(
                r"\besop\b|employee stock ownership",
                f"{nearest_heading}\n{chunk_text}",
                re.IGNORECASE,
            )
        )
        if not justified:
            unjustified += 1
        print(
            f"{chunk_id}\tjustified={justified}\tstored={stored_tags}"
            f"\tsection={section_ref}\n"
            f"  own-text={chunk_text[:240].replace(chr(10), ' ')}"
        )
    print(f"Unjustified ESOP tags: {unjustified}")
    if unjustified:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
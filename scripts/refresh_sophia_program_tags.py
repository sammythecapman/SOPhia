#!/usr/bin/env python3
"""Refresh SOPhia heading-derived program metadata without changing embeddings."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts" / "api-server"))
from applicability import classify_text  # noqa: E402
from db import connection  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha256", required=True, help="Expected current corpus hash; prevents updating another corpus.")
    parser.add_argument("--edition", default="SOP 50 10 8.1")
    parser.add_argument("--apply", action="store_true", help="Apply metadata changes to the DEVELOPMENT database only.")
    args = parser.parse_args()
    if args.apply and (
        os.getenv("NODE_ENV", "").casefold() == "production"
        or os.getenv("REPLIT_DEPLOYMENT", "") == "1"
    ):
        raise RuntimeError("Production writes are not supported by this development utility.")
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, section_ref, chunk_text, program_scopes, product_lines "
            "FROM sop_chunks WHERE sop_version = %s AND corpus_sha256 = %s",
            (args.edition, args.sha256),
        ).fetchall()
        if not rows:
            raise RuntimeError("No rows match the expected edition and corpus hash.")
        changed = []
        for row in rows:
            tags = classify_text(row[2], row[1])
            if list(row[3] or []) == tags["program_scopes"] and list(row[4] or []) == tags["product_lines"]:
                continue
            changed.append({"id": row[0], "section": row[1], "program_scopes": tags["program_scopes"], "product_lines": tags["product_lines"]})
            if args.apply:
                conn.execute(
                    "UPDATE sop_chunks SET program_scopes = %s, product_lines = %s "
                    "WHERE id = %s AND sop_version = %s AND corpus_sha256 = %s",
                    (tags["program_scopes"], tags["product_lines"], row[0], args.edition, args.sha256),
                )
    print(json.dumps({"mode": "applied" if args.apply else "preview", "chunks_checked": len(rows), "chunks_changed": len(changed), "changes": changed}, indent=2))


if __name__ == "__main__":
    main()

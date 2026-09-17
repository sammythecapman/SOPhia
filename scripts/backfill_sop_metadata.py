#!/usr/bin/env python3
"""Backfill source version, effective date, and TOC page numbers for ingested chunks."""

import argparse
import sys
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "artifacts" / "api-server"))
from db import connection  # noqa: E402
from ingest_sop import extract_source_metadata, normalize_heading_title  # noqa: E402


def build_page_lookup(document: Document) -> dict[str, int]:
    _, _, toc_pages = extract_source_metadata(document)
    return toc_pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--from-version", default="SOP 50 10 8")
    parser.add_argument("--version", default="SOP 50 10 8.1")
    parser.add_argument("--effective-date", default="2026-10-01")
    args = parser.parse_args()

    document = Document(args.path)
    page_lookup = build_page_lookup(document)
    updated = 0
    missing_pages: set[str] = set()

    with connection() as conn:
        refs = conn.execute(
            "SELECT DISTINCT section_ref FROM sop_chunks WHERE sop_version = %s",
            (args.from_version,),
        ).fetchall()
        with conn.transaction():
            for (section_ref,) in refs:
                page_number = 1 if section_ref == "Document introduction" else None
                if page_number is None:
                    for heading in reversed(section_ref.split(" > ")):
                        page_number = page_lookup.get(normalize_heading_title(heading))
                        if page_number is not None:
                            break
                if page_number is None:
                    missing_pages.add(section_ref)
                result = conn.execute(
                    """
                    UPDATE sop_chunks
                    SET sop_version = %s, effective_date = %s, page_number = %s
                    WHERE sop_version = %s AND section_ref = %s
                    """,
                    (args.version, args.effective_date, page_number, args.from_version, section_ref),
                )
                updated += result.rowcount

    print(f"Updated {updated} chunks to {args.version} effective {args.effective_date}.")
    if missing_pages:
        print(f"No TOC page found for {len(missing_pages)} section references.")


if __name__ == "__main__":
    main()
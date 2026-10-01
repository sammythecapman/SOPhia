import hashlib
import unittest
from pathlib import Path

from docx import Document

from scripts.ingest_sop import (
    DEFAULT_SOURCE_URL,
    extract_chunks,
    extract_source_metadata,
)
from source_metadata import canonicalize_source_url


ROOT = Path(__file__).resolve().parents[1]
TECHNICAL_UPDATE = (
    ROOT
    / "attached_assets"
    / "SOP_50_10_8.1_Technical_Policy_Updates_effective_10.1.2026.docx"
)


class TechnicalSourceTests(unittest.TestCase):
    def test_technical_revision_metadata_and_hash_are_pinned(self):
        self.assertEqual(
            hashlib.sha256(TECHNICAL_UPDATE.read_bytes()).hexdigest(),
            "0fb0c4692cf529380827746e5fe812e42ea82b6f6fdf97a71d1093677d963183",
        )
        version, effective_date, _ = extract_source_metadata(
            Document(TECHNICAL_UPDATE)
        )
        self.assertEqual(version, "SOP 50 10 8.1")
        self.assertEqual(effective_date, "2026-10-01")
        self.assertEqual(
            DEFAULT_SOURCE_URL,
            "https://www.sba.gov/document/sop-50-10-lender-development-company-loan-programs",
        )
        self.assertEqual(
            canonicalize_source_url("https://www.sba.gov/document/sop-50-10-8-1"),
            DEFAULT_SOURCE_URL,
        )
        self.assertEqual(
            canonicalize_source_url("https://example.com/custom-source"),
            "https://example.com/custom-source",
        )

    def test_technical_trust_aggregation_and_robs_rules_are_present(self):
        chunks = extract_chunks(TECHNICAL_UPDATE)
        trust_rules = [
            chunk
            for chunk in chunks
            if "one or more trusts" in chunk["chunk_text"].casefold()
            and "in the aggregate" in chunk["chunk_text"].casefold()
        ]
        robs_rules = [
            chunk
            for chunk in chunks
            if "full unconditional guaranty of the sponsor" in chunk["chunk_text"].casefold()
        ]
        self.assertEqual(len(trust_rules), 1)
        self.assertEqual(trust_rules[0]["page_number"], 93)
        self.assertIn("each trust must provide", trust_rules[0]["chunk_text"].casefold())
        self.assertEqual(len(robs_rules), 1)
        self.assertEqual(robs_rules[0]["page_number"], 47)


if __name__ == "__main__":
    unittest.main()
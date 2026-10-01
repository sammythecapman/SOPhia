import hashlib
import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from docx import Document

from scripts import ingest_sop
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


class AtomicIngestTests(unittest.TestCase):
    def test_upsert_stale_cleanup_and_metadata_commit_together(self):
        events = []
        connection = FakeConnection(events)

        class FakeEmbeddings:
            def create(self, model, input):
                events.append("embed")
                return SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.0]) for _ in input]
                )

        client = SimpleNamespace(embeddings=FakeEmbeddings())
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "test-only",
                    "DATABASE_URL": "postgresql://test-only",
                },
            ),
            patch("scripts.ingest_sop.OpenAI", return_value=client),
            patch("scripts.ingest_sop.connection", return_value=connection),
        ):
            ingest_sop.ingest(
                [minimal_chunk()],
                "SOP 50 10 8.1",
                "2026-10-01",
                DEFAULT_SOURCE_URL,
                "new-source-hash",
            )

        self.assertEqual(
            events,
            ["embed", "connect", "begin", "upsert", "delete", "metadata", "commit"],
        )
        delete_query, delete_params, in_transaction = connection.calls[1]
        self.assertIn("DELETE FROM sop_chunks", delete_query)
        self.assertIn("corpus_sha256 IS DISTINCT FROM %s", delete_query)
        self.assertEqual(delete_params, ("SOP 50 10 8.1", "new-source-hash"))
        self.assertTrue(in_transaction)
        self.assertTrue(all(call[2] for call in connection.calls))

    def test_embedding_quota_failure_does_not_open_database(self):
        connection = patch("scripts.ingest_sop.connection")
        error = RuntimeError("quota")
        error.code = "credit_balance_exhausted"
        error.body = {"error": {"type": "insufficient_quota"}}

        class FailedEmbeddings:
            def create(self, model, input):
                raise error

        client = SimpleNamespace(embeddings=FailedEmbeddings())
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "test-only",
                    "DATABASE_URL": "postgresql://test-only",
                },
            ),
            patch("scripts.ingest_sop.OpenAI", return_value=client),
            connection as connection_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "quota"):
                ingest_sop.ingest(
                    [minimal_chunk()],
                    "SOP 50 10 8.1",
                    "2026-10-01",
                    DEFAULT_SOURCE_URL,
                    "new-source-hash",
                )
        connection_mock.assert_not_called()


class FakeConnection:
    def __init__(self, events):
        self.events = events
        self.calls = []
        self.in_transaction = False

    def __enter__(self):
        self.events.append("connect")
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    @contextmanager
    def transaction(self):
        self.events.append("begin")
        self.in_transaction = True
        try:
            yield
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
        finally:
            self.in_transaction = False

    def execute(self, query, params):
        if "DELETE FROM sop_chunks" in query:
            self.events.append("delete")
            cursor = SimpleNamespace(rowcount=17)
        elif "INSERT INTO corpus_metadata" in query:
            self.events.append("metadata")
            cursor = SimpleNamespace(rowcount=1)
        else:
            self.events.append("upsert")
            cursor = SimpleNamespace(rowcount=1)
        self.calls.append((query, params, self.in_transaction))
        return cursor


def minimal_chunk():
    return {
        "section_ref": "Test section",
        "chunk_text": "Test content",
        "page_number": 1,
        "transaction_types": [],
        "entity_structures": [],
        "party_roles": [],
        "program_scopes": [],
        "product_lines": [],
        "loan_size_bands": [],
    }


if __name__ == "__main__":
    unittest.main()
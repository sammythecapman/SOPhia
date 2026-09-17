#!/usr/bin/env python3
"""Preview and, only after explicit approval, ingest SBA SOP 50 10 8."""

import argparse
import datetime as dt
import hashlib
import os
import random
import re
import sys
import time
from pathlib import Path

from docx import Document
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "artifacts" / "api-server"))
from applicability import APPLICABILITY_DIMENSIONS, classify_text  # noqa: E402
from db import connection  # noqa: E402

MODEL = "text-embedding-3-small"
MAX_CHARS = 6000
BATCH_SIZE = 64
STRUCTURAL_HEADING_RE = re.compile(r"^heading [1-6]$")
DEFAULT_EFFECTIVE_DATE = "2026-10-01"


def find_docx(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    candidates = sorted(Path("attached_assets").glob("*.docx"))
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected exactly one .docx in attached_assets; found {len(candidates)}. "
            "Pass the path explicitly."
        )
    return candidates[0]


def is_heading(paragraph) -> bool:
    text = paragraph.text.strip()
    style = (paragraph.style.name or "").lower()
    return bool(text and STRUCTURAL_HEADING_RE.fullmatch(style))


def normalize_heading_title(text: str) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^[A-Z]\.\s*", "", value)


def extract_source_metadata(document: Document) -> tuple[str | None, str | None, dict[str, int]]:
    version = None
    effective_date = None
    toc_pages: dict[str, int] = {}
    in_toc = False

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        if "version:" in text.casefold():
            match = re.search(r"Version:\s*([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
            if match:
                version = f"SOP 50 10 {match.group(1)}"
        if text.casefold().startswith("effective date:"):
            raw_date = text.split(":", 1)[1].strip()
            try:
                effective_date = dt.datetime.strptime(raw_date, "%B %d, %Y").date().isoformat()
            except ValueError:
                effective_date = raw_date
        if text.casefold() == "table of contents":
            in_toc = True
            continue
        if in_toc and paragraph.style.name.casefold().startswith("toc"):
            parts = re.split(r"\t+", text)
            if len(parts) >= 2 and parts[-1].strip().isdigit():
                title = parts[-2].strip()
                toc_pages[normalize_heading_title(title)] = int(parts[-1].strip())
            continue
        if in_toc and is_heading(paragraph):
            in_toc = False

    return version, effective_date, toc_pages


def page_for_heading(heading_stack: list[str], toc_pages: dict[str, int]) -> int | None:
    if not heading_stack:
        return 1
    for heading in reversed(heading_stack):
        page = toc_pages.get(normalize_heading_title(heading))
        if page is not None:
            return page
    return None


def split_text(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    paragraphs, chunks, current = text.split("\n"), [], ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 1 > MAX_CHARS:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def extract_chunks(path: Path) -> list[dict[str, str]]:
    document = Document(path)
    _, _, toc_pages = extract_source_metadata(document)
    heading_stack: list[str] = []
    body: list[str] = []
    output: list[dict[str, str]] = []
    in_table_of_contents = False

    def flush() -> None:
        nonlocal body
        text = "\n".join(body).strip()
        if text:
            ref = " > ".join(heading_stack) or "Document introduction"
            for part in split_text(text):
                item = {
                    "section_ref": ref,
                    "chunk_text": part,
                    "page_number": page_for_heading(heading_stack, toc_pages),
                }
                item.update(classify_text(part, ref))
                output.append(item)
        body = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower()
        if text.casefold() == "table of contents" and "heading" in style:
            flush()
            heading_stack = []
            in_table_of_contents = True
            continue
        if in_table_of_contents and style.startswith("toc"):
            continue
        if in_table_of_contents:
            in_table_of_contents = False
        if is_heading(paragraph):
            flush()
            level_match = re.search(r"(\d+)", paragraph.style.name or "")
            level = int(level_match.group(1)) if level_match else 1
            heading_stack[:] = heading_stack[: max(0, level - 1)]
            heading_stack.append(text)
        else:
            body.append(text)
    flush()
    return output


def embed_with_retry(client: OpenAI, texts: list[str]) -> list[list[float]]:
    for attempt in range(6):
        try:
            response = client.embeddings.create(model=MODEL, input=texts)
            return [item.embedding for item in response.data]
        except Exception:
            if attempt == 5:
                raise
            delay = min(30, (2**attempt) + random.random())
            print(f"Embedding request failed; retrying in {delay:.1f}s...")
            time.sleep(delay)
    raise RuntimeError("Embedding retry loop exhausted")


def ingest(chunks: list[dict[str, str]], version: str, effective_date: str | None) -> None:
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("DATABASE_URL"):
        raise RuntimeError("OPENAI_API_KEY and DATABASE_URL are required for ingestion.")
    client = OpenAI()
    inserted = 0
    with connection() as conn:
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            embeddings = embed_with_retry(client, [item["chunk_text"] for item in batch])
            with conn.transaction():
                for item, embedding in zip(batch, embeddings):
                    conn.execute(
                        """
                        INSERT INTO sop_chunks
                            (sop_version, section_ref, chunk_text, effective_date, page_number,
                             transaction_types, entity_structures, party_roles, program_scopes,
                             embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (sop_version, section_ref, chunk_hash)
                        DO UPDATE SET embedding = EXCLUDED.embedding
                        """,
                        (
                            version,
                            item["section_ref"],
                            item["chunk_text"],
                            effective_date,
                            item["page_number"],
                            item["transaction_types"],
                            item["entity_structures"],
                            item["party_roles"],
                            item["program_scopes"],
                            embedding,
                        ),
                    )
                    inserted += 1
            print(f"Processed {min(start + BATCH_SIZE, len(chunks))}/{len(chunks)} chunks")
    print(f"Ingestion complete: {inserted} chunks inserted or refreshed.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?")
    parser.add_argument("--version", default="SOP 50 10 8.1")
    parser.add_argument("--effective-date", default=DEFAULT_EFFECTIVE_DATE)
    parser.add_argument("--preview-count", type=int, default=8)
    parser.add_argument("--ingest", action="store_true", help="Enable approval prompt and ingestion")
    args = parser.parse_args()
    path = find_docx(args.path)
    chunks = extract_chunks(path)
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    print(f"Document: {path} ({len(chunks)} chunks, fingerprint {fingerprint})")
    for index, chunk in enumerate(chunks[: args.preview_count], 1):
        preview = chunk["chunk_text"][:350].replace("\n", " ")
        print(f"\n[{index}] {chunk['section_ref']}\n{preview}")
    if not args.ingest:
        print("\nPREVIEW ONLY: no embeddings requested and no database rows written.")
        print("Review the chunks, then rerun with --ingest to receive an approval prompt.")
        return
    confirmation = input(
        f'\nType exactly "INGEST {args.version}" to embed and upsert all {len(chunks)} chunks: '
    )
    if confirmation != f"INGEST {args.version}":
        print("Approval not received. No embeddings requested and no rows written.")
        return
    ingest(chunks, args.version, args.effective_date)


if __name__ == "__main__":
    main()
"""Ingestion: Markdown reports with page markers -> page-aware chunks with metadata -> Qdrant.

Report files look like:
    ---
    id: R-101
    title: ...
    ---
    <!-- page: 1 -->
    text...
Metadata (sector, market, region, year) is taken from the MySQL `reports` table, which is the
source of truth for the catalogue; a file whose id is not in the catalogue is skipped.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.logging_setup import log_event
from app.security.injection import find_injection

logger = logging.getLogger(__name__)

FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
PAGE_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
MAX_CHARS = 900


def parse_report(text: str) -> tuple[dict, list[tuple[int, str]]]:
    meta: dict[str, str] = {}
    m = FRONT_RE.match(text)
    body = text
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    parts = PAGE_RE.split(body)
    pages = []
    # parts = [preamble, page_no, text, page_no, text, ...]
    for i in range(1, len(parts) - 1, 2):
        page_text = parts[i + 1].strip()
        if page_text:
            pages.append((int(parts[i]), page_text))
    return meta, pages


def chunk_page(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Paragraph-packing chunker; the last paragraph is carried over as overlap."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    for para in paras:
        if current and len("\n\n".join(current + [para])) > max_chars:
            chunks.append("\n\n".join(current))
            current = [current[-1]] if len(current[-1]) < max_chars // 3 else []
        current.append(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def build_chunks(path: Path, catalog: dict[str, dict]) -> tuple[str | None, list[dict], list[dict]]:
    meta, pages = parse_report(path.read_text(encoding="utf-8"))
    rid = meta.get("id")
    if not rid or rid not in catalog:
        log_event(logger, "ingest_skip_unknown_report", logging.WARNING, file=path.name, report_id=rid)
        return None, [], []
    rep = catalog[rid]
    chunks, flags = [], []
    for page_no, page_text in pages:
        for idx, text in enumerate(chunk_page(page_text)):
            hit = find_injection(text)
            if hit:
                flags.append({"report_id": rid, "page": page_no, "fragment": hit})
            chunks.append({
                "chunk_id": f"{rid}:p{page_no}:c{idx}",
                "report_id": rid,
                "title": rep["title"],
                "publisher": rep["publisher"],
                "sector": rep["sector"],
                "market": rep["market"],
                "region": rep["region"],
                "year": int(str(rep["published"])[:4]),
                "page": page_no,
                "chunk_index": idx,
                "injection_flag": bool(hit),
                "text": text,
            })
    return rid, chunks, flags


def ingest_directory(reports_dir: str, repo, store) -> dict:
    catalog = repo.get_catalog()
    files = sorted(Path(reports_dir).glob("*.md"))
    all_chunks: list[dict] = []
    all_flags: list[dict] = []
    reports: list[str] = []
    for f in files:
        rid, chunks, flags = build_chunks(f, catalog)
        if rid:
            reports.append(rid)
            all_chunks += chunks
            all_flags += flags
    store.reset()
    if all_chunks:
        store.upsert(all_chunks)
    for fl in all_flags:
        repo.log_security_event(
            event_type="injection_in_document",
            source=f"{fl['report_id']} p.{fl['page']} (ingest)",
            detail=f"Instruction-like text found during ingestion: '{fl['fragment']}'. "
                   "Chunk is flagged; text is stripped before any LLM call.",
        )
    log_event(logger, "ingest_complete", reports=reports, chunks=len(all_chunks), injection_flags=len(all_flags))
    return {"reports": reports, "chunks": len(all_chunks), "injection_flags": all_flags}

"""Qdrant vector store. Entitlement filtering happens inside the vector query (payload filter),
so chunks from reports the client has not bought are never returned to Python, let alone the LLM."""
from __future__ import annotations

import re
import uuid

from qdrant_client import QdrantClient, models

from app.domain import Chunk
from app.rag.embeddings import Embedder

STOPWORDS = {
    "the", "and", "for", "what", "which", "will", "was", "were", "with", "that", "this", "from", "your",
    "are", "how", "much", "many", "does", "did", "have", "has", "market", "report", "reports", "about",
    "be", "is", "in", "of", "to", "a", "an", "on", "by", "it", "worth", "should", "i", "we", "our",
}


def _terms(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9\-]+", text.lower()) if len(t) > 2 and t not in STOPWORDS}


class VectorStore:
    def __init__(self, url: str, collection: str, embedder: Embedder):
        self.client = QdrantClient(url=url, timeout=10)
        self.collection = collection
        self.embedder = embedder

    def count(self) -> int:
        if not self.client.collection_exists(self.collection):
            return 0
        return self.client.count(self.collection, exact=True).count

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:  # noqa: BLE001 - health check
            return False

    def reset(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            self.collection,
            vectors_config=models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE),
        )
        for field in ("report_id", "market", "sector", "region"):
            self.client.create_payload_index(self.collection, field_name=field,
                                             field_schema=models.PayloadSchemaType.KEYWORD)
        for field in ("year", "page"):
            self.client.create_payload_index(self.collection, field_name=field,
                                             field_schema=models.PayloadSchemaType.INTEGER)

    def upsert(self, chunks: list[dict]) -> None:
        vectors = self.embedder.embed_passages([c["text"] for c in chunks])
        points = [
            models.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, c["chunk_id"])), vector=v, payload=c)
            for c, v in zip(chunks, vectors)
        ]
        self.client.upsert(self.collection, points=points, wait=True)

    def search(self, query: str, report_ids: list[str], k: int, page: int | None = None) -> list[Chunk]:
        """Dense search restricted to `report_ids`, then a light lexical re-rank (hybrid-lite)."""
        if not report_ids:
            return []
        must = [models.FieldCondition(key="report_id", match=models.MatchAny(any=report_ids))]
        if page is not None:
            must.append(models.FieldCondition(key="page", match=models.MatchValue(value=page)))
        flt = models.Filter(must=must)
        hits = self.client.query_points(
            self.collection,
            query=self.embedder.embed_query(query),
            query_filter=flt,
            limit=k * 3,
            with_payload=True,
        ).points
        q_terms = _terms(query)
        scored = []
        for h in hits:
            p = h.payload or {}
            if p.get("report_id") not in report_ids:  # belt and braces
                continue
            overlap = len(q_terms & _terms(p.get("text", ""))) / max(1, len(q_terms))
            scored.append((0.8 * float(h.score) + 0.2 * overlap, float(h.score), p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            Chunk(
                cid="",
                report_id=p["report_id"],
                title=p.get("title", ""),
                publisher=p.get("publisher", ""),
                page=int(p.get("page", 0)),
                text=p.get("text", ""),
                score=round(dense, 4),
            )
            for _, dense, p in scored[:k]
        ]

"""Local embeddings with fastembed (ONNX, CPU). No API key, no per-token cost, model baked into the image."""
from __future__ import annotations


class Embedder:
    def __init__(self, model_name: str, cache_dir: str):
        from fastembed import TextEmbedding  # heavy import kept lazy for unit tests

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.dim = len(self.embed_query("dimension probe"))

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()

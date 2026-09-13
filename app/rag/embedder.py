"""Code embedder providing Gemini embedding API and deterministic offline fallback."""

import os
import math
import hashlib
from typing import List
import numpy as np


class CodeEmbedder:
    """Generates embedding vectors for code snippets using Gemini or deterministic fallback."""

    def __init__(self, dimension: int = 128, use_gemini: bool = False):
        self.dimension = dimension
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.use_gemini = use_gemini and bool(self.api_key)

        if self.use_gemini:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
            except Exception:
                self.use_gemini = False

    def embed_text(self, text: str) -> np.ndarray:
        """Generates an L2-normalized embedding vector for a single text string."""
        if self.use_gemini:
            try:
                import google.generativeai as genai
                response = genai.embed_content(
                    model="models/text-embedding-004",
                    content=text,
                    task_type="retrieval_document",
                )
                vec = np.array(response["embedding"], dtype=np.float32)
                return self._l2_normalize(vec)
            except Exception:
                pass  # Fall back to deterministic n-gram vector if API call fails

        return self._deterministic_ngram_embedding(text)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Generates L2-normalized embedding vectors for a batch of text strings."""
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)

        vectors = [self.embed_text(t) for t in texts]
        return np.vstack(vectors)

    def _deterministic_ngram_embedding(self, text: str) -> np.ndarray:
        """Generates a deterministic 128-dim n-gram feature hash embedding for offline usage."""
        vec = np.zeros(self.dimension, dtype=np.float32)
        words = text.lower().split()
        if not words:
            vec[0] = 1.0
            return vec

        # Feature hashing of unigrams and bigrams
        for i, word in enumerate(words):
            # Unigram hash
            idx1 = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16) % self.dimension
            vec[idx1] += 1.0

            # Bigram hash
            if i > 0:
                bigram = f"{words[i-1]}_{word}"
                idx2 = int(hashlib.md5(bigram.encode("utf-8")).hexdigest(), 16) % self.dimension
                vec[idx2] += 1.5

        return self._l2_normalize(vec)

    @staticmethod
    def _l2_normalize(vec: np.ndarray) -> np.ndarray:
        """L2 normalizes a vector."""
        norm = np.linalg.norm(vec)
        if norm > 0:
            return (vec / norm).astype(np.float32)
        return vec.astype(np.float32)

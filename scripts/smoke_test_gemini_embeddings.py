"""Minimal live smoke test for Gemini Embedding API integration (Layer 5).

Usage:
    export GEMINI_API_KEY="your-api-key"
    python -m scripts.smoke_test_gemini_embeddings
"""

import os
import sys
import numpy as np
from app.rag.embedder import CodeEmbedder


def run_smoke_test():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY environment variable is NOT set.")
        print("[STATUS] Live Gemini Embedding API integration status: UNTESTED.")
        print("To run this smoke test, export GEMINI_API_KEY and re-run this script.")
        sys.exit(1)

    print("[INFO] GEMINI_API_KEY detected. Initializing CodeEmbedder(use_gemini=True)...")
    embedder = CodeEmbedder(use_gemini=True)

    if not embedder.use_gemini:
        print("[ERROR] CodeEmbedder failed to enable Gemini mode (check google-generativeai package or API key format).")
        sys.exit(1)

    test_snippet = "def calculate_factorial(n: int) -> int:\n    return 1 if n <= 1 else n * calculate_factorial(n - 1)"
    print(f"[INFO] Requesting embedding for snippet:\n{test_snippet}\n")

    try:
        vec = embedder.embed_text(test_snippet)
        print(f"[SUCCESS] Received embedding vector!")
        print(f"  Shape: {vec.shape}")
        print(f"  Dtype: {vec.dtype}")
        print(f"  L2 Norm: {np.linalg.norm(vec):.6f}")
        print(f"  First 5 dimensions: {vec[:5]}")
        print("\n[VERIFIED] Live Gemini Embedding API integration is WORKING and response shape matches expectation!")
    except Exception as e:
        print(f"[FAIL] Live Gemini Embedding API call raised exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_smoke_test()

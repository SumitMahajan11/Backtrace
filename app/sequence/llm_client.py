"""Lightweight LLM provider adapter using httpx (Layer 6 Stage D)."""

import os
from typing import Callable, Optional
import httpx

NarrationLLMCallable = Callable[[str, str], str]  # (system_prompt, user_prompt) -> raw_response_text


def create_ollama_provider(
    model: str = "llama3.2:3b",
    base_url: str = "http://127.0.0.1:11434",
    timeout: float = 120.0,
) -> NarrationLLMCallable:
    """Creates a NarrationLLMCallable backed by a local Ollama daemon."""
    def ollama_callable(system_prompt: str, user_prompt: str) -> str:
        url = f"{base_url.rstrip('/')}/api/generate"
        payload = {
            "model": model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")

    return ollama_callable


def get_default_llm_provider() -> Optional[NarrationLLMCallable]:
    """
    Detects available LLM providers in priority order:
    1. Local Ollama if active on 127.0.0.1:11434.
    2. None (falls back to deterministic template).
    """
    # Check for local Ollama
    try:
        with httpx.Client(timeout=1.0) as client:
            res = client.get("http://127.0.0.1:11434/api/tags")
            if res.status_code == 200:
                tags = res.json().get("models", [])
                model_names = [m.get("name", "") for m in tags]
                if not model_names:
                    return None
                chosen_model = model_names[0]
                for name in model_names:
                    if "llama" in name:
                        chosen_model = name
                        break
                return create_ollama_provider(model=chosen_model)
    except Exception:
        pass

    return None

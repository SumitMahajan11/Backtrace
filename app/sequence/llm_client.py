import logging
import os
from typing import Callable, Optional
import httpx

logger = logging.getLogger(__name__)

NarrationLLMCallable = Callable[[str, str], str]  # (system_prompt, user_prompt) -> raw_response_text


def create_groq_provider(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 20.0,
) -> NarrationLLMCallable:
    """Creates a NarrationLLMCallable backed by the Groq API (POST /openai/v1/chat/completions)."""
    def groq_callable(system_prompt: str, user_prompt: str) -> str:
        key = api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")
        if not key or not str(key).strip():
            logger.error("Groq provider error: MissingApiKeyError")
            raise ValueError("MissingApiKeyError")

        chosen_model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b") or "openai/gpt-oss-20b"
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {str(key).strip()}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                choices = data.get("choices")
                if not choices or not isinstance(choices, list):
                    logger.error("Groq provider error: EmptyReplyError")
                    raise ValueError("EmptyReplyError")
                content = choices[0].get("message", {}).get("content", "")
                if not content or not str(content).strip():
                    logger.error("Groq provider error: EmptyReplyError")
                    raise ValueError("EmptyReplyError")
                return content
        except Exception as exc:
            # Log ONLY the error type, never the key or the prompt
            logger.error("Groq provider error: %s", type(exc).__name__)
            raise

    return groq_callable


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
    1. Groq if LLM_PROVIDER=groq.
    2. Local Ollama if active on 127.0.0.1:11434.
    3. None (falls back to deterministic template).
    """
    provider_env = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider_env == "groq":
        return create_groq_provider()

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

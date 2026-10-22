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
    Detects configured LLM provider:
    1. Groq if LLM_PROVIDER=groq.
    2. Local Ollama if LLM_PROVIDER=ollama (probes local Ollama on 127.0.0.1:11434 or configured base URL).
    3. None if LLM_PROVIDER is unset or any other value (makes no network call).
    """
    provider_env = ""
    base_url = "http://127.0.0.1:11434"
    configured_model = "llama3.2:3b"
    timeout = 120.0
    try:
        from app.core.config import get_settings
        settings = get_settings()
        if hasattr(settings, "OLLAMA_TIMEOUT") and settings.OLLAMA_TIMEOUT is not None:
            timeout = float(settings.OLLAMA_TIMEOUT)
        if settings.LLM_PROVIDER:
            provider_env = str(settings.LLM_PROVIDER).strip().lower()
        if hasattr(settings, "OLLAMA_BASE_URL") and settings.OLLAMA_BASE_URL:
            base_url = str(settings.OLLAMA_BASE_URL).strip()
        if hasattr(settings, "OLLAMA_MODEL") and settings.OLLAMA_MODEL:
            configured_model = str(settings.OLLAMA_MODEL).strip()
    except Exception:
        timeout = 120.0

    # Environment variable overrides
    env_override = os.getenv("LLM_PROVIDER", "").strip().lower()
    if env_override:
        provider_env = env_override

    base_url = os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_ENDPOINT", base_url)).strip()
    env_model = os.getenv("OLLAMA_MODEL")
    if env_model is not None and env_model.strip():
        configured_model = env_model.strip()
    elif env_model is not None and not env_model.strip():
        configured_model = "llama3.2:3b"
    if not configured_model:
        configured_model = "llama3.2:3b"

    if os.getenv("OLLAMA_TIMEOUT"):
        try:
            timeout = float(os.getenv("OLLAMA_TIMEOUT", str(timeout)))
        except ValueError:
            pass

    if provider_env == "groq":
        return create_groq_provider()
    elif provider_env == "ollama":
        tags_url = f"{base_url.rstrip('/')}/api/tags"
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(tags_url)
                if res.status_code == 200:
                    tags = res.json().get("models", [])
                    model_names = [m.get("name", "") for m in tags]
                    if not model_names:
                        return None

                    # Prefer configured model if present in available tags
                    chosen_model = None
                    for name in model_names:
                        if name == configured_model or name.startswith(f"{configured_model}:") or configured_model.startswith(f"{name}:"):
                            chosen_model = name
                            break

                    if not chosen_model:
                        for name in model_names:
                            if "llama" in name:
                                chosen_model = name
                                break

                    if not chosen_model:
                        chosen_model = model_names[0]

                    return create_ollama_provider(model=chosen_model, base_url=base_url, timeout=timeout)
        except Exception as exc:
            logger.warning("Ollama probe to %s failed: %s", tags_url, exc)

    return None

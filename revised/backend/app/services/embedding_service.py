import logging
import time
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def get_text_embedding(text: str) -> Optional[list[float]]:
    """Compute dense float embedding vector using local Gemma server (llama.cpp or Ollama)."""
    if not text or not text.strip():
        return None

    cleaned_text = text.strip()[:1500]
    timeout_sec = getattr(settings, "GEMMA_TIMEOUT", 60.0)

    # 1. Try standard OpenAI-compatible /v1/embeddings endpoint
    if settings.GEMMA_API_URL:
        api_url = settings.GEMMA_API_URL.rstrip("/")
        for model_candidate in [settings.GEMMA_MODEL_ID, "gemma-2-2b-it-Q4_K_M.gguf", ""]:
            payload = {"input": cleaned_text}
            if model_candidate:
                payload["model"] = model_candidate
            try:
                with httpx.Client(timeout=timeout_sec) as client:
                    resp = client.post(f"{api_url}/v1/embeddings", json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("data", [])
                        if items and isinstance(items[0], dict) and "embedding" in items[0]:
                            emb = items[0]["embedding"]
                            if isinstance(emb, list) and len(emb) > 0:
                                return [float(x) for x in emb]
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.debug("OpenAI embedding connect issue (%s): %s", api_url, e)
                break
            except Exception as e:
                logger.debug("OpenAI embeddings endpoint error: %s", e)

        # 2. Try native llama.cpp /embedding endpoint as fallback
        try:
            payload_native = {"content": cleaned_text}
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.post(f"{api_url}/embedding", json=payload_native)
                if resp.status_code == 200:
                    data = resp.json()
                    emb = data.get("embedding")
                    if isinstance(emb, list) and len(emb) > 0:
                        # In case of nested lists [[...]]
                        if isinstance(emb[0], list):
                            emb = emb[0]
                        return [float(x) for x in emb]
        except Exception as e:
            logger.debug("Gemma native /embedding generation skipped: %s", e)

    # 3. Try Ollama embeddings endpoint as fallback
    ollama_candidates = [settings.OLLAMA_URL] if settings.OLLAMA_URL else []
    if "http://localhost:11434" not in ollama_candidates and "http://127.0.0.1:11434" not in ollama_candidates:
        ollama_candidates.append("http://localhost:11434")

    for o_url in ollama_candidates:
        if not o_url:
            continue
        try:
            cleaned_o_url = o_url.rstrip("/")
            with httpx.Client(timeout=timeout_sec) as client:
                resp = client.post(
                    f"{cleaned_o_url}/api/embeddings",
                    json={"model": settings.GEMMA_MODEL_ID, "prompt": cleaned_text},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    emb = data.get("embedding")
                    if isinstance(emb, list) and len(emb) > 0:
                        return [float(x) for x in emb]
        except Exception as e:
            logger.debug("Ollama embedding skipped for %s: %s", o_url, e)

    return None

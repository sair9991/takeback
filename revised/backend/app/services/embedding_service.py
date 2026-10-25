import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def get_text_embedding(text: str) -> Optional[list[float]]:
    """Compute dense float embedding vector using local Gemma server."""
    if not text or not text.strip():
        return None

    cleaned_text = text.strip()[:4000]
    api_url = settings.GEMMA_API_URL.rstrip("/")

    # 1. Try standard OpenAI-compatible /v1/embeddings endpoint
    try:
        payload = {
            "input": cleaned_text,
            "model": settings.GEMMA_MODEL_ID,
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{api_url}/v1/embeddings", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", [])
                if items and isinstance(items[0], dict) and "embedding" in items[0]:
                    return items[0]["embedding"]
    except Exception as e:
        logger.debug("OpenAI-compatible embeddings endpoint error: %s", e)

    # 2. Try native llama.cpp /embedding endpoint as fallback
    try:
        payload = {"content": cleaned_text}
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{api_url}/embedding", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                if "embedding" in data and isinstance(data["embedding"], list):
                    return data["embedding"]
    except Exception as e:
        logger.warning("Gemma embedding generation failed: %s", e)

    return None

"""Optional Groq LLM summarizer for news headlines."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a financial news analyst. Summarize the following news headline "
    "and any available context into 1-2 concise sentences focused on market impact. "
    "Be specific about what changed, who is affected, and why it matters for traders."
)


class Summarizer:
    """Summarize news headlines using Groq's free LLM API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama-3.1-8b-instant",
        max_tokens: int = 150,
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        self.max_tokens = max_tokens
        self._available = bool(self.api_key)
        if self._available:
            self._client = httpx.Client(
                base_url="https://api.groq.com/openai/v1",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )

    @property
    def available(self) -> bool:
        return self._available

    def summarize(self, title: str, context: str = "") -> str | None:
        """Generate a 1-2 sentence summary of a headline.

        Returns None if Groq API is unavailable or the call fails.
        """
        if not self._available:
            return None

        user_content = f"Headline: {title}"
        if context:
            user_content += f"\nContext: {context}"

        try:
            response = self._client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": self.max_tokens,
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning("Summarizer failed for '%s': %s", title[:60], e)
            return None

    def summarize_batch(self, items: list[dict]) -> list[tuple[str, str | None]]:
        """Summarize a batch of news items.

        Returns list of (item_id, summary) tuples.
        """
        results = []
        for item in items:
            summary = self.summarize(item["title"])
            results.append((item["item_id"], summary))
        return results

    def close(self):
        if self._available:
            self._client.close()

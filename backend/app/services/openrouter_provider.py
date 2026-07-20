import httpx

from app.core.config import get_settings
from app.services.review_provider import ReviewProvider

settings = get_settings()


class OpenRouterReviewProvider(ReviewProvider):
    """Call an online review model through OpenRouter."""

    def __init__(self, http_client: httpx.AsyncClient, model_name: str) -> None:
        self.http_client = http_client
        self.model_name = model_name

    async def review_content(self, content: str) -> str:
        # Keep the prompt small and focused so free models can respond reliably.
        response = await self.http_client.post(
            f"{settings.open_router_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.open_router_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.app_public_url,
                "X-OpenRouter-Title": settings.app_name,
            },
            json={
                "model": self.model_name,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert code reviewer. "
                            "Review the provided pull request diff carefully. "
                            "Focus on correctness, bugs, security risks, performance issues, "
                            "and maintainability concerns. "
                            "When possible, mention file names in your findings."
                        ),
                    },
                    {
                        "role": "user",
                        "content": content,
                    },
                ],
            },
            timeout=120.0,
        )
        response.raise_for_status()

        payload = response.json()
        return payload["choices"][0]["message"]["content"]

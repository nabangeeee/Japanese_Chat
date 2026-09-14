"""Application inference through OpenAI Responses (not Hermes maintenance)."""
import time
import re
from urllib.parse import quote, urlsplit
from typing import Any
from openai import OpenAI, APIConnectionError, APIStatusError

MODEL = "gpt-6-astra"


class ProviderOutputError(RuntimeError):
    """A completed, nonempty answer was not returned by the provider."""


def generate_text(api_key: str, prompt: str, *, instructions: str = "",
                  history: list | None = None, web_search: bool = False,
                  max_output_tokens: int = 2048,
                  json_schema: dict | None = None) -> str:
    messages = [
        {"role": item["role"], "content": item["content"]}
        for item in (history or [])[-10:]
        if isinstance(item, dict) and item.get("role") in ("user", "assistant")
        and isinstance(item.get("content"), str) and item["content"]
    ]
    messages.append({"role": "user", "content": prompt})
    kwargs: dict[str, Any] = dict(model=MODEL, input=messages, instructions=instructions,
                  store=False, reasoning={"effort": "low"},
                  max_output_tokens=max_output_tokens)
    if web_search:
        kwargs["tools"] = [{"type": "web_search"}]
    if json_schema is not None:
        kwargs["text"] = {"format": {"type": "json_schema", "name": "result",
                                      "schema": json_schema, "strict": True}}
    with OpenAI(api_key=api_key, timeout=60.0, max_retries=0) as client:
        for attempt in range(3):
            try:
                response = client.responses.create(**kwargs)
                if response.status != "completed" or not response.output_text.strip():
                    raise ProviderOutputError("OpenAI returned incomplete or empty output")
                text = response.output_text
                if web_search:
                    urls = []
                    for item in getattr(response, "output", []):
                        if item.type != "message":
                            continue
                        for part in item.content:
                            for annotation in getattr(part, "annotations", []):
                                if annotation.type == "url_citation":
                                    url = annotation.url
                                    if urlsplit(url).scheme in ("http", "https") and url not in urls:
                                        urls.append(url)
                    if urls:
                        # Canonical links survive Japanese cleanup and DB reloads.
                        text = re.sub(r'\[([^\]]+)\]\(https?://[^\s)]+\)', r'\1', text)
                        text += " " + " ".join(
                            f"[出典 {i}]({quote(url, safe=':/?&=#%+-._~')})"
                            for i, url in enumerate(urls, 1)
                        )
                return text
            except (APIConnectionError, APIStatusError) as exc:
                transient = isinstance(exc, APIConnectionError) or exc.status_code in (408, 409, 429) or exc.status_code >= 500
                if not transient or attempt == 2:
                    raise
                time.sleep(1.0 * (2 ** attempt))
    raise RuntimeError("OpenAI generation failed")

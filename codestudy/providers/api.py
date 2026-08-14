"""Provider API HTTP (Anthropic o OpenAI-compatibile).

Predisposto ma NON attivo di default. La chiave si legge dalla variabile
d'ambiente indicata in config (`api_key_env`) — mai scritta nel file.
Usa solo stdlib (urllib) per non aggiungere dipendenze.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict

from .base import AIProvider, ProviderError, RateLimitError


class ApiProvider(AIProvider):
    name = "api"

    def __init__(self, cfg: Dict[str, Any]):
        self.base_url = cfg.get("base_url", "https://api.anthropic.com/v1/messages")
        self.kind = cfg.get("kind", "anthropic")  # "anthropic" | "openai"
        self.model = cfg.get("model", "")
        self.api_key_env = cfg.get("api_key_env", "ANTHROPIC_API_KEY")
        self.timeout = int(cfg.get("timeout_seconds", 600))
        self.max_tokens = int(cfg.get("max_tokens", 4096))

    def _api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "") if self.api_key_env else ""
        if not key:
            raise ProviderError(
                f"Provider 'api' attivo ma la variabile d'ambiente "
                f"'{self.api_key_env}' non e' impostata."
            )
        return key

    def analyze(self, prompt: str, context: str = "") -> str:
        full = self._compose(prompt, context)
        if self.kind == "anthropic":
            return self._anthropic(full)
        return self._openai(full)

    # ---- Anthropic Messages API ----
    def _anthropic(self, text: str) -> str:
        key = self._api_key()
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": text}],
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        data = self._post(self.base_url, body, headers)
        parts = data.get("content", [])
        out = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        return out

    # ---- OpenAI-compatibile ----
    def _openai(self, text: str) -> str:
        key = self._api_key()
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": text}],
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {key}",
        }
        data = self._post(self.base_url, body, headers)
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""

    def _post(self, url: str, body: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        raw = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=raw, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code == 429:
                raise RateLimitError(f"HTTP 429: {detail}") from e
            raise ProviderError(f"HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise ProviderError(f"Errore di rete verso {url}: {e.reason}") from e

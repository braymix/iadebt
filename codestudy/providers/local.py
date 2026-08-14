"""Provider modello locale via endpoint OpenAI-compatibile (Ollama / LM Studio).

E' un caso particolare del provider OpenAI-compatibile che punta a localhost.
Selezionabile per privacy/offline. Di norma non richiede API key.
"""

from __future__ import annotations

from typing import Any, Dict

from .api import ApiProvider


class LocalProvider(ApiProvider):
    name = "local"

    def __init__(self, cfg: Dict[str, Any]):
        cfg = dict(cfg)
        cfg.setdefault("kind", "openai")
        cfg.setdefault("base_url", "http://localhost:11434/v1/chat/completions")
        cfg.setdefault("api_key_env", "")  # tipicamente non serve
        super().__init__(cfg)

    def _api_key(self) -> str:
        # I server locali di norma non richiedono chiave: se assente, stringa vuota.
        import os

        if self.api_key_env:
            return os.environ.get(self.api_key_env, "") or ""
        return ""

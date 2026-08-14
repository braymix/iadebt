"""Provider di default: invoca il CLI `claude` in modalita' headless.

Sintassi verificata (claude 2.1.x):
    claude -p "<prompt>" --output-format json [--model <m>]
`--output-format json` ritorna un oggetto con il campo `result` (testo finale).
Sfrutta l'abbonamento gia' configurato: nessuna API key necessaria.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Dict, List

from .base import AIProvider, ProviderError, RateLimitError


class ClaudeCliProvider(AIProvider):
    name = "claude-code-cli"

    def __init__(self, cfg: Dict[str, Any]):
        self.command = cfg.get("command", "claude")
        self.model = cfg.get("model", "") or ""
        self.extra_args: List[str] = list(cfg.get("extra_args", []) or [])
        self.timeout = int(cfg.get("timeout_seconds", 600))

    def _build_argv(self, full_prompt: str) -> List[str]:
        argv = [self.command, "-p", full_prompt, "--output-format", "json"]
        if self.model:
            argv += ["--model", self.model]
        argv += self.extra_args
        return argv

    def analyze(self, prompt: str, context: str = "") -> str:
        if shutil.which(self.command) is None:
            raise ProviderError(
                f"CLI '{self.command}' non trovato nel PATH. Installa Claude Code "
                f"oppure imposta un altro provider in config."
            )
        full = self._compose(prompt, context)
        argv = self._build_argv(full)
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderError(f"Timeout ({self.timeout}s) invocando il CLI claude.") from e

        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            if _looks_rate_limited(stderr):
                raise RateLimitError(f"Limite d'uso del CLI: {stderr[:400]}")
            raise ProviderError(
                f"CLI claude uscito con codice {proc.returncode}: {stderr[:800]}"
            )

        stdout = (proc.stdout or "").strip()
        if not stdout:
            raise ProviderError("Il CLI claude non ha prodotto output.")

        # --output-format json => oggetto con campo `result`
        try:
            obj = json.loads(stdout)
        except json.JSONDecodeError:
            # fallback: alcune versioni possono stampare testo puro
            return stdout

        if isinstance(obj, dict):
            if obj.get("is_error") or obj.get("subtype") == "error_max_turns":
                msg = str(obj.get("result") or obj.get("error") or "errore CLI")
                if _looks_rate_limited(msg):
                    raise RateLimitError(msg[:400])
                raise ProviderError(f"CLI claude ha segnalato errore: {msg[:400]}")
            result = obj.get("result")
            if isinstance(result, str):
                return result
        return stdout


def _looks_rate_limited(text: str) -> bool:
    t = (text or "").lower()
    return any(
        k in t
        for k in ("rate limit", "usage limit", "429", "too many requests", "overloaded")
    )

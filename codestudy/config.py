"""Caricamento configurazione YAML con default e override da ambiente.

Regola: NESSUN segreto in chiaro nel file. Le chiavi API si leggono da
variabili d'ambiente indicate in config (campo `api_key_env`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml


DEFAULT_CONFIG: Dict[str, Any] = {
    "provider": "claude-code-cli",
    "output_dir": "./codestudy-output",
    "commit_range": "HEAD~10..HEAD",
    "path_filters": [],          # limita l'analisi a questi path/moduli (prefissi)
    "workers": 1,                # parallelismo chiamate AI
    "max_retries": 4,
    "backoff_base_seconds": 2.0,
    "max_payload_chars": 24000,  # tronca payload molto grandi prima dell'invio
    "providers": {
        "claude-code-cli": {
            "command": "claude",
            "model": "",          # vuoto = default del CLI
            "extra_args": [],
            "timeout_seconds": 600,
        },
        "api": {
            "base_url": "https://api.anthropic.com/v1/messages",
            "kind": "anthropic",  # "anthropic" | "openai"
            "model": "claude-sonnet-5",
            "api_key_env": "ANTHROPIC_API_KEY",
            "timeout_seconds": 600,
            "max_tokens": 4096,
        },
        "local": {
            "base_url": "http://localhost:11434/v1/chat/completions",
            "model": "llama3.1",
            "api_key_env": "",    # di norma non serve per Ollama/LM Studio
            "timeout_seconds": 600,
            "max_tokens": 4096,
        },
    },
}


@dataclass
class Config:
    raw: Dict[str, Any] = field(default_factory=dict)

    # ---- accessi comodi ----
    @property
    def provider(self) -> str:
        return self.raw["provider"]

    @property
    def output_dir(self) -> str:
        return self.raw["output_dir"]

    @property
    def commit_range(self) -> str:
        return self.raw["commit_range"]

    @property
    def path_filters(self) -> List[str]:
        return list(self.raw.get("path_filters") or [])

    @property
    def workers(self) -> int:
        return int(self.raw.get("workers", 1))

    @property
    def max_retries(self) -> int:
        return int(self.raw.get("max_retries", 4))

    @property
    def backoff_base_seconds(self) -> float:
        return float(self.raw.get("backoff_base_seconds", 2.0))

    @property
    def max_payload_chars(self) -> int:
        return int(self.raw.get("max_payload_chars", 24000))

    def provider_config(self, name: Optional[str] = None) -> Dict[str, Any]:
        name = name or self.provider
        return dict(self.raw.get("providers", {}).get(name, {}))


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Optional[str]) -> Config:
    """Carica config da file (se esiste) fondendola sui default."""
    data: Dict[str, Any] = {}
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    merged = _deep_merge(DEFAULT_CONFIG, data)
    return Config(raw=merged)


def example_yaml() -> str:
    """YAML di esempio commentato, per `codestudy init-config`."""
    return EXAMPLE_YAML


EXAMPLE_YAML = """\
# ===== CodeStudy — configurazione =====
# Motore AI attivo. Il resto del tool e' identico per ogni provider.
#   claude-code-cli : usa il CLI `claude` in headless (nessuna API key)
#   api             : API HTTP (Anthropic/OpenAI) - chiave via env
#   local           : endpoint OpenAI-compatibile (Ollama / LM Studio)
provider: claude-code-cli

output_dir: ./codestudy-output
commit_range: HEAD~10..HEAD      # default per la modalita' incrementale
path_filters: []                 # es. ["src/main/java/com/acme/debts"]

workers: 1                       # parallelismo chiamate AI (alza con cautela)
max_retries: 4
backoff_base_seconds: 2.0
max_payload_chars: 24000

providers:
  claude-code-cli:
    command: claude
    model: ""                    # vuoto = default del CLI
    extra_args: []
    timeout_seconds: 600

  api:
    base_url: https://api.anthropic.com/v1/messages
    kind: anthropic              # "anthropic" | "openai"
    model: claude-sonnet-5
    api_key_env: ANTHROPIC_API_KEY   # <-- la chiave si legge da QUI, mai in chiaro
    timeout_seconds: 600
    max_tokens: 4096

  local:
    base_url: http://localhost:11434/v1/chat/completions
    model: llama3.1
    api_key_env: ""
    timeout_seconds: 600
    max_tokens: 4096
"""

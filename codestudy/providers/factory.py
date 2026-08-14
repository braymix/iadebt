"""Selezione del provider da configurazione."""

from __future__ import annotations

from ..config import Config
from .base import AIProvider, ProviderError
from .claude_cli import ClaudeCliProvider
from .api import ApiProvider
from .local import LocalProvider


def build_provider(config: Config) -> AIProvider:
    name = config.provider
    pcfg = config.provider_config(name)
    if name == "claude-code-cli":
        return ClaudeCliProvider(pcfg)
    if name == "api":
        return ApiProvider(pcfg)
    if name == "local":
        return LocalProvider(pcfg)
    raise ProviderError(
        f"Provider sconosciuto: '{name}'. Validi: claude-code-cli, api, local."
    )

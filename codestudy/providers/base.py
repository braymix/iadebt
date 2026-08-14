"""Interfaccia unica dei provider AI.

Tutto il resto del tool dipende SOLO da questa interfaccia:
    analyze(prompt, context) -> testo
Cambiare provider cambia solo il "motore", mai la logica di git/analisi/output.
"""

from __future__ import annotations

import abc


class ProviderError(RuntimeError):
    """Errore generico del provider (subprocess fallito, HTTP != 2xx, ...)."""


class RateLimitError(ProviderError):
    """Il provider ha segnalato un limite d'uso: il runner applica il backoff."""


class AIProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def analyze(self, prompt: str, context: str = "") -> str:
        """Esegue una chiamata e ritorna il testo grezzo della risposta.

        `context` viene anteposto a `prompt`. Le implementazioni non devono
        interpretare il contenuto: il parsing dell'eventuale JSON e' a valle.
        """
        raise NotImplementedError

    # utilita' comune alle implementazioni
    @staticmethod
    def _compose(prompt: str, context: str) -> str:
        if context:
            return f"{context}\n\n{prompt}"
        return prompt

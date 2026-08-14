"""Modelli dati condivisi. Nessuna logica di provider o di I/O qui dentro."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Flashcard:
    """Una flashcard front/back. Deve testare la ricostruzione del flusso."""

    front: str
    back: str
    tags: str = ""

    @staticmethod
    def from_obj(obj: dict) -> "Flashcard":
        return Flashcard(
            front=str(obj.get("front", "")).strip(),
            back=str(obj.get("back", "")).strip(),
            tags=str(obj.get("tags", "")).strip(),
        )


@dataclass
class AnalysisResult:
    """Output normalizzato di una singola analisi (un 'blocco logico')."""

    summary: str = ""
    technical_flow: str = ""
    business_flow: str = ""
    flashcards: List[Flashcard] = field(default_factory=list)
    mermaid: str = ""
    notes_markdown: str = ""

    @staticmethod
    def from_obj(obj: dict) -> "AnalysisResult":
        cards = [Flashcard.from_obj(c) for c in obj.get("flashcards", []) if isinstance(c, dict)]
        return AnalysisResult(
            summary=str(obj.get("summary", "")).strip(),
            technical_flow=str(obj.get("technical_flow", "")).strip(),
            business_flow=str(obj.get("business_flow", "")).strip(),
            flashcards=cards,
            mermaid=str(obj.get("mermaid", "")).strip(),
            notes_markdown=str(obj.get("notes_markdown", "")).strip(),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(s: str) -> "AnalysisResult":
        return AnalysisResult.from_obj(json.loads(s))


@dataclass
class Unit:
    """Unità di lavoro atomica (= una chiamata AI). Chiave di ripresa/stato."""

    key: str          # identificatore stabile, es. "file::src/Foo.java"
    title: str        # titolo leggibile per output/log
    kind: str         # "file_delta" | "file_summary" | "dir_summary" | "architecture"
    payload: str      # contenuto da analizzare (diff, sorgente, riassunti aggregati)
    language: str = "generic"
    extra: dict = field(default_factory=dict)

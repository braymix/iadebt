"""Generazione flashcard in formato neutro: CSV stile Anki + markdown."""

from __future__ import annotations

import csv
import os
from typing import List, Tuple

from ..models import Flashcard


def write_flashcards(out_dir: str, deck: str,
                     cards: List[Tuple[str, Flashcard]]) -> Tuple[str, str]:
    """Scrive CSV (front,back,tags,deck) e markdown speculare.

    `cards` e' una lista di (titolo_blocco, Flashcard). Ritorna i due path.
    """
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "flashcards.csv")
    md_path = os.path.join(out_dir, "flashcards.md")

    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["front", "back", "tags", "deck"])
        for _title, c in cards:
            w.writerow([c.front, c.back, c.tags, deck])

    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Flashcard — {deck}\n\n")
        fh.write(
            "> Principio: queste flashcard testano la ricostruzione del flusso, "
            "non il \"cosa fa X\". Usale con richiamo attivo.\n\n"
        )
        current = None
        for title, c in cards:
            if title != current:
                fh.write(f"\n## {title}\n\n")
                current = title
            fh.write(f"**Q:** {c.front}\n\n")
            fh.write(f"**A:** {c.back}\n\n")
            if c.tags:
                fh.write(f"`{c.tags}`\n\n")
            fh.write("---\n\n")

    return csv_path, md_path

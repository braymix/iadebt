"""Generazione mappe in sintassi Mermaid (testo, versionabile)."""

from __future__ import annotations

import os
import re
from typing import List, Tuple


def _clean_mermaid(text: str) -> str:
    """Rimuove eventuali fence ```mermaid lasciati dal modello."""
    t = text.strip()
    t = re.sub(r"^```(?:mermaid)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def write_map(out_dir: str, blocks: List[Tuple[str, str]]) -> str:
    """Scrive un unico markdown con una mappa Mermaid per blocco.

    `blocks` = lista di (titolo, mermaid_source). Ritorna il path.
    """
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "maps.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Mappe (Mermaid)\n\n")
        for title, mermaid in blocks:
            m = _clean_mermaid(mermaid)
            if not m:
                continue
            fh.write(f"## {title}\n\n")
            fh.write("```mermaid\n")
            fh.write(m + "\n")
            fh.write("```\n\n")
    return path


def write_architecture_map(out_dir: str, mermaid: str) -> str:
    """Mappa dell'architettura macro (modalita' intero software)."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "architecture.md")
    m = _clean_mermaid(mermaid)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Architettura macro\n\n")
        if m:
            fh.write("```mermaid\n")
            fh.write(m + "\n")
            fh.write("```\n")
    return path

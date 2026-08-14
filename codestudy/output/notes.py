"""Generazione note di studio in markdown (flusso tecnico + dominio)."""

from __future__ import annotations

import os
from typing import List, Tuple

from ..models import AnalysisResult


def write_notes(out_dir: str, run_title: str,
                blocks: List[Tuple[str, AnalysisResult]]) -> str:
    """Scrive una nota discorsiva per ogni blocco. Ritorna il path."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "notes.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# Note di studio — {run_title}\n\n")
        for title, res in blocks:
            fh.write(f"## {title}\n\n")
            if res.summary:
                fh.write(f"{res.summary}\n\n")
            if res.technical_flow:
                fh.write(f"**Flusso tecnico**\n\n{res.technical_flow}\n\n")
            if res.business_flow:
                fh.write(f"**Flusso di business/dominio**\n\n{res.business_flow}\n\n")
            if res.notes_markdown:
                fh.write(f"{res.notes_markdown}\n\n")
            fh.write("---\n\n")
    return path

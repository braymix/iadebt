"""Modalita' incrementale: costruisce le unita' di lavoro dal delta di commit.

Un 'blocco logico di modifica' = un file modificato (diff aggregato). Granularita'
comoda per ripresa, flashcard e mini-mappa per pezzo toccato.

La selezione puo' essere:
- un range (`HEAD~10..HEAD`, `<sha>..HEAD`, ...), oppure
- una lista di commit espliciti: in tal caso ogni (commit, file) e' un blocco a se',
  cosi' si vede l'effetto di ciascun commit separatamente.

Ogni blocco viene classificato per dimensione: le modifiche piccole ricevono una
spiegazione minimale (vedi `Unit.extra["minimal"]`), quelle grandi il flusso completo.
"""

from __future__ import annotations

from typing import List, Optional

from ..config import Config
from ..models import Unit
from ..stack import StackRule, load_rules, rule_for_file
from ..vcs import (
    changed_files,
    changed_files_in_commit,
    file_diff,
    file_diff_in_commit,
)


def build_incremental_units(repo: str, commit_range: Optional[str], config: Config,
                            stack: StackRule,
                            commits: Optional[List[str]] = None) -> List[Unit]:
    rules = load_rules()
    units: List[Unit] = []

    if commits:
        for sha in commits:
            short = sha[:8]
            for path in changed_files_in_commit(repo, sha, config.path_filters):
                unit = _make_delta_unit(
                    repo, path, file_diff_in_commit(repo, sha, path), stack, rules, config,
                    key=f"file_delta::{sha}::{path}",
                    title=f"{short} · {path}",
                    commit=short,
                )
                if unit:
                    units.append(unit)
    else:
        for path in changed_files(repo, commit_range, config.path_filters):
            unit = _make_delta_unit(
                repo, path, file_diff(repo, commit_range, path), stack, rules, config,
                key=f"file_delta::{path}", title=path,
            )
            if unit:
                units.append(unit)

    return units


def _make_delta_unit(repo: str, path: str, diff: str, stack: StackRule, rules,
                     config: Config, *, key: str, title: str,
                     commit: Optional[str] = None) -> Optional[Unit]:
    if not diff.strip():
        return None
    changed = _count_changed_lines(diff)
    diff = _truncate(diff, config.max_payload_chars)
    frule = rule_for_file(path, rules)
    lang = frule.language if frule.name != "generic" else stack.language
    extra = {
        "minimal": changed <= config.minimal_threshold,
        "changed_lines": changed,
    }
    if commit:
        extra["commit"] = commit
    return Unit(key=key, title=title, kind="file_delta", payload=diff,
                language=lang, extra=extra)


def _count_changed_lines(diff: str) -> int:
    """Righe effettivamente aggiunte/rimosse (esclusi header di file `+++`/`---`)."""
    n = 0
    for line in diff.splitlines():
        if not line or line.startswith("+++") or line.startswith("---"):
            continue
        if line[0] in "+-":
            n += 1
    return n


def _truncate(text: str, limit: int) -> str:
    if limit and len(text) > limit:
        return text[:limit] + "\n\n[... troncato per limite di dimensione ...]"
    return text

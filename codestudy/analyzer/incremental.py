"""Modalita' incrementale: costruisce le unita' di lavoro dal delta di commit.

Un 'blocco logico di modifica' = un file modificato nel range (diff aggregato).
Granularita' comoda per ripresa, flashcard e mini-mappa per pezzo toccato.
"""

from __future__ import annotations

from typing import List

from ..config import Config
from ..models import Unit
from ..stack import StackRule, load_rules, rule_for_file
from ..vcs import changed_files, file_diff


def build_incremental_units(repo: str, commit_range: str, config: Config,
                            stack: StackRule) -> List[Unit]:
    rules = load_rules()
    files = changed_files(repo, commit_range, config.path_filters)
    units: List[Unit] = []
    for path in files:
        diff = file_diff(repo, commit_range, path)
        if not diff.strip():
            continue
        diff = _truncate(diff, config.max_payload_chars)
        frule = rule_for_file(path, rules)
        lang = frule.language if frule.name != "generic" else stack.language
        units.append(
            Unit(
                key=f"file_delta::{path}",
                title=path,
                kind="file_delta",
                payload=diff,
                language=lang,
            )
        )
    return units


def _truncate(text: str, limit: int) -> str:
    if limit and len(text) > limit:
        return text[:limit] + "\n\n[... troncato per limite di dimensione ...]"
    return text

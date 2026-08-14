"""Rilevamento dello stack, language-agnostic ed estendibile.

Le regole di tracciamento del flusso stanno in `rules/*.yaml`: aggiungere un
linguaggio = aggiungere un file YAML (nessuna modifica al codice). Il rilevamento
usa i manifest/di build e il conteggio delle estensioni dei sorgenti. Se nulla
combacia, si degrada a `generic`.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


RULES_DIR = os.path.join(os.path.dirname(__file__), "rules")


@dataclass
class StackRule:
    name: str
    language: str
    extensions: List[str] = field(default_factory=list)
    manifests: List[str] = field(default_factory=list)
    manifest_hints: List[str] = field(default_factory=list)
    entrypoint_markers: List[str] = field(default_factory=list)
    layer_markers: List[str] = field(default_factory=list)
    flow_hint: str = ""

    @staticmethod
    def from_dict(d: dict) -> "StackRule":
        return StackRule(
            name=d.get("name", "generic"),
            language=d.get("language", "generic"),
            extensions=list(d.get("extensions", []) or []),
            manifests=list(d.get("manifests", []) or []),
            manifest_hints=list(d.get("manifest_hints", []) or []),
            entrypoint_markers=list(d.get("entrypoint_markers", []) or []),
            layer_markers=list(d.get("layer_markers", []) or []),
            flow_hint=(d.get("flow_hint", "") or "").strip(),
        )


def load_rules(rules_dir: str = RULES_DIR) -> List[StackRule]:
    rules: List[StackRule] = []
    if not os.path.isdir(rules_dir):
        return rules
    for fn in sorted(os.listdir(rules_dir)):
        if not fn.endswith((".yaml", ".yml")):
            continue
        with open(os.path.join(rules_dir, fn), "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        rules.append(StackRule.from_dict(data))
    return rules


def _generic(rules: List[StackRule]) -> StackRule:
    for r in rules:
        if r.name == "generic":
            return r
    return StackRule(name="generic", language="generic",
                     flow_hint="Analisi generica basata sul diff/sorgente.")


def detect_stack(repo: str, files: Optional[List[str]] = None,
                 rules_dir: str = RULES_DIR) -> StackRule:
    """Rileva la regola dominante del repo.

    Punteggio = presenza di manifest (peso alto) + n. di sorgenti per estensione.
    `files` opzionale restringe il conteggio (es. ai soli file del range).
    """
    rules = load_rules(rules_dir)
    if not rules:
        return _generic(rules)

    # elenco file su cui ragionare
    if files is None:
        files = _walk_files(repo)

    ext_counts: Counter = Counter(os.path.splitext(f)[1].lower() for f in files)
    basenames = {os.path.basename(f) for f in files}
    all_names = set(files) | basenames

    best: Optional[StackRule] = None
    best_score = 0
    for rule in rules:
        if rule.name == "generic":
            continue
        score = 0
        for m in rule.manifests:
            # match per suffisso (.csproj) o per nome file esatto
            if any(n.endswith(m) or n == m for n in all_names):
                score += 50
        for ext in rule.extensions:
            score += ext_counts.get(ext, 0)
        if score > best_score:
            best_score = score
            best = rule

    if best is None or best_score == 0:
        return _generic(rules)
    return best


def rule_for_file(path: str, rules: List[StackRule]) -> StackRule:
    """Regola applicabile a un singolo file (per file di linguaggio misto)."""
    ext = os.path.splitext(path)[1].lower()
    for rule in rules:
        if rule.name == "generic":
            continue
        if ext in rule.extensions:
            return rule
    return _generic(rules)


def _walk_files(repo: str, limit: int = 5000) -> List[str]:
    out: List[str] = []
    skip = {".git", "node_modules", "target", "bin", "obj", ".venv", "dist", "build"}
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in skip]
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), repo)
            out.append(rel)
            if len(out) >= limit:
                return out
    return out

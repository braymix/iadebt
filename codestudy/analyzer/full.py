"""Modalita' intero software (onboarding): mappatura gerarchica bottom-up.

Poiche' l'intero codebase non entra in un singolo prompt, si procede a livelli:
  L1  file_summary  -> un riassunto per file sorgente
  L2  dir_summary   -> aggrega i riassunti dei file per cartella/modulo
  L3  architecture  -> aggrega i riassunti dei moduli + punti d'ingresso

Il runner esegue una fase per volta, passando i risultati alla fase successiva.
La ripresa funziona perche' i risultati sono persistiti nello store.
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Dict, List

from ..config import Config
from ..models import AnalysisResult, Unit
from ..stack import StackRule, load_rules, rule_for_file
from ..vcs import list_tracked_files, read_file_at_head

ARCH_KIND = "architecture"

# estensioni considerate "sorgente" per la mappatura (evita binari/asset)
_SOURCE_EXTS = {
    ".java", ".cs", ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rb",
    ".php", ".kt", ".scala", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".swift", ".m", ".mm", ".vb", ".fs",
}


def _is_source(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _SOURCE_EXTS


def build_file_units(repo: str, config: Config, stack: StackRule) -> List[Unit]:
    """L1: una unita' per file sorgente tracciato (filtrata su path_filters)."""
    rules = load_rules()
    files = [f for f in list_tracked_files(repo, config.path_filters) if _is_source(f)]
    units: List[Unit] = []
    for path in files:
        content = read_file_at_head(repo, path)
        if not content.strip():
            continue
        content = _truncate(content, config.max_payload_chars)
        frule = rule_for_file(path, rules)
        lang = frule.language if frule.name != "generic" else stack.language
        units.append(
            Unit(
                key=f"file_summary::{path}",
                title=path,
                kind="file_summary",
                payload=content,
                language=lang,
                extra={"dir": os.path.dirname(path) or "."},
            )
        )
    return units


def build_dir_units(file_units: List[Unit],
                    file_results: Dict[str, AnalysisResult]) -> List[Unit]:
    """L2: aggrega i riassunti dei file per cartella immediata."""
    by_dir: Dict[str, List[str]] = defaultdict(list)
    for u in file_units:
        res = file_results.get(u.key)
        if res is None:
            continue
        d = u.extra.get("dir", ".")
        block = (
            f"- `{u.title}`: {res.summary}\n"
            f"    tecnico: {res.technical_flow[:400]}\n"
            f"    dominio: {res.business_flow[:400]}"
        )
        by_dir[d].append(block)

    units: List[Unit] = []
    for d in sorted(by_dir):
        payload = "\n".join(by_dir[d])
        units.append(
            Unit(
                key=f"dir_summary::{d}",
                title=d,
                kind="dir_summary",
                payload=payload,
                extra={"dir": d},
            )
        )
    return units


def build_arch_unit(dir_units: List[Unit],
                    dir_results: Dict[str, AnalysisResult],
                    entrypoints: List[str]) -> Unit:
    """L3: un'unica unita' che sintetizza l'architettura macro."""
    lines: List[str] = []
    for u in dir_units:
        res = dir_results.get(u.key)
        if res is None:
            continue
        lines.append(f"### Modulo `{u.title}`\n{res.summary}\n{res.technical_flow[:500]}")
    if entrypoints:
        lines.append("### Punti d'ingresso rilevati\n" + "\n".join(f"- {e}" for e in entrypoints[:50]))
    payload = "\n\n".join(lines)
    return Unit(
        key="architecture::root",
        title="Architettura macro",
        kind=ARCH_KIND,
        payload=payload,
    )


def find_entrypoints(repo: str, config: Config, stack: StackRule) -> List[str]:
    """Cerca marcatori di entrypoint (routing/controller) nei file sorgente."""
    if not stack.entrypoint_markers:
        return []
    markers = stack.entrypoint_markers
    found: List[str] = []
    files = [f for f in list_tracked_files(repo, config.path_filters) if _is_source(f)]
    for path in files:
        content = read_file_at_head(repo, path)
        if not content:
            continue
        for m in markers:
            if m in content:
                found.append(f"{path} ({m})")
                break
    return found


def _truncate(text: str, limit: int) -> str:
    if limit and len(text) > limit:
        return text[:limit] + "\n\n[... troncato per limite di dimensione ...]"
    return text


def build_full_units(repo: str, config: Config, stack: StackRule) -> List[Unit]:
    """Comodo per la stima costi: numero totale di unita' L1+L2(stimato)+L3.

    La costruzione reale e' a fasi nel runner; qui stimiamo per la conferma.
    """
    file_units = build_file_units(repo, config, stack)
    dirs = {u.extra.get("dir", ".") for u in file_units}
    # L1 (file) + L2 (una per cartella) + L3 (architettura)
    est = list(file_units)
    # placeholder per stima: non ancora eseguibili senza risultati L1
    for d in sorted(dirs):
        est.append(Unit(key=f"dir_summary::{d}", title=d, kind="dir_summary", payload=""))
    est.append(Unit(key="architecture::root", title="Architettura macro",
                    kind=ARCH_KIND, payload=""))
    return est

"""Orchestrazione: ripresa, parallelismo con backoff, throttling, output.

Indipendente dal provider concreto: riceve un AIProvider e lavora su Unit.
"""

from __future__ import annotations

import concurrent.futures as cf
import time
from typing import Callable, Dict, List, Tuple

from .analyzer import full as full_mod
from .analyzer.incremental import build_incremental_units
from .analyzer.prompts import build_prompt, parse_result
from .config import Config
from .models import AnalysisResult, Unit
from .output import (
    write_architecture_map,
    write_flashcards,
    write_map,
    write_notes,
)
from .providers.base import AIProvider, ProviderError, RateLimitError
from .stack import StackRule, load_rules, rule_for_file
from .state import StateStore


Logger = Callable[[str], None]


def _rule_by_lang(language: str) -> StackRule:
    for r in load_rules():
        if r.language == language and r.name != "generic":
            return r
    for r in load_rules():
        if r.name == "generic":
            return r
    return StackRule(name="generic", language="generic")


def _execute_one(provider: AIProvider, unit: Unit, config: Config) -> AnalysisResult:
    rule = _rule_by_lang(unit.language)
    prompt = build_prompt(unit, rule)
    last_err: Exception = ProviderError("errore sconosciuto")
    for attempt in range(config.max_retries + 1):
        try:
            raw = provider.analyze(prompt)
            return parse_result(raw)
        except RateLimitError as e:
            last_err = e
            wait = config.backoff_base_seconds * (2 ** attempt)
            time.sleep(wait)
        except ProviderError as e:
            last_err = e
            wait = config.backoff_base_seconds * (2 ** attempt)
            time.sleep(min(wait, 8))
    raise last_err


def execute_units(units: List[Unit], provider: AIProvider, config: Config,
                  store: StateStore, run_id: str, log: Logger) -> Dict[str, AnalysisResult]:
    """Esegue una lista di unita' con ripresa e parallelismo. Ritorna i risultati."""
    results: Dict[str, AnalysisResult] = {}
    todo: List[Unit] = []
    for u in units:
        cached = store.get_result(run_id, u.key)
        if cached is not None:
            results[u.key] = cached
            log(f"  = salto (gia' fatto): {u.title}")
        else:
            todo.append(u)

    if not todo:
        return results

    workers = max(1, config.workers)

    def work(u: Unit) -> Tuple[Unit, AnalysisResult]:
        return u, _execute_one(provider, u, config)

    if workers == 1:
        for u in todo:
            _process(u, work, store, run_id, results, log)
    else:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(work, u): u for u in todo}
            for fut in cf.as_completed(futs):
                u = futs[fut]
                try:
                    _, res = fut.result()
                    results[u.key] = res
                    store.save_done(run_id, u.key, u.kind, u.title, res)
                    log(f"  + fatto: {u.title}")
                except Exception as e:  # noqa: BLE001
                    store.save_error(run_id, u.key, u.kind, u.title, str(e))
                    log(f"  ! errore su {u.title}: {e}")
    return results


def _process(u: Unit, work, store: StateStore, run_id: str,
             results: Dict[str, AnalysisResult], log: Logger) -> None:
    try:
        _, res = work(u)
        results[u.key] = res
        store.save_done(run_id, u.key, u.kind, u.title, res)
        log(f"  + fatto: {u.title}")
    except Exception as e:  # noqa: BLE001
        store.save_error(run_id, u.key, u.kind, u.title, str(e))
        log(f"  ! errore su {u.title}: {e}")


# ---------------------------------------------------------------- output

def _collect_and_write(out_dir: str, deck: str, run_title: str,
                       ordered: List[Tuple[str, AnalysisResult]]) -> List[str]:
    cards = []
    maps = []
    for title, res in ordered:
        for c in res.flashcards:
            cards.append((title, c))
        if res.mermaid:
            maps.append((title, res.mermaid))
    paths: List[str] = []
    if cards:
        csv_p, md_p = write_flashcards(out_dir, deck, cards)
        paths += [csv_p, md_p]
    if maps:
        paths.append(write_map(out_dir, maps))
    paths.append(write_notes(out_dir, run_title, ordered))
    return paths


# ---------------------------------------------------------------- incrementale

def run_incremental(repo: str, commit_range: str, config: Config, provider: AIProvider,
                    store: StateStore, run_id: str, out_dir: str, stack: StackRule,
                    log: Logger) -> List[str]:
    units = build_incremental_units(repo, commit_range, config, stack)
    if not units:
        log("Nessuna modifica nel range: niente da analizzare.")
        return []
    log(f"Analizzo {len(units)} blocchi (file modificati) con provider '{provider.name}'.")
    results = execute_units(units, provider, config, store, run_id, log)
    ordered = [(u.title, results[u.key]) for u in units if u.key in results]
    return _collect_and_write(out_dir, f"codestudy::{run_id}", f"delta {commit_range}", ordered)


# ---------------------------------------------------------------- intero software

def run_full(repo: str, config: Config, provider: AIProvider, store: StateStore,
             run_id: str, out_dir: str, stack: StackRule, log: Logger) -> List[str]:
    # L1: file
    file_units = full_mod.build_file_units(repo, config, stack)
    if not file_units:
        log("Nessun file sorgente trovato: niente da analizzare.")
        return []
    log(f"[L1] Riassunto di {len(file_units)} file...")
    file_results = execute_units(file_units, provider, config, store, run_id, log)

    # L2: cartelle
    dir_units = full_mod.build_dir_units(file_units, file_results)
    log(f"[L2] Sintesi di {len(dir_units)} moduli/cartelle...")
    dir_results = execute_units(dir_units, provider, config, store, run_id, log)

    # L3: architettura
    entrypoints = full_mod.find_entrypoints(repo, config, stack)
    arch_unit = full_mod.build_arch_unit(dir_units, dir_results, entrypoints)
    log("[L3] Mappa dell'architettura macro...")
    arch_results = execute_units([arch_unit], provider, config, store, run_id, log)

    # output: note+flashcard+mappe per file e per modulo; mappa architettura a parte
    ordered: List[Tuple[str, AnalysisResult]] = []
    for u in file_units:
        if u.key in file_results:
            ordered.append((f"file: {u.title}", file_results[u.key]))
    for u in dir_units:
        if u.key in dir_results:
            ordered.append((f"modulo: {u.title}", dir_results[u.key]))

    paths = _collect_and_write(out_dir, f"codestudy::{run_id}", "intero software", ordered)

    arch = arch_results.get(arch_unit.key)
    if arch and arch.mermaid:
        paths.append(write_architecture_map(out_dir, arch.mermaid))
    return paths


# ---------------------------------------------------------------- stima costi

def estimate_incremental(repo: str, commit_range: str, config: Config,
                         stack: StackRule) -> int:
    return len(build_incremental_units(repo, commit_range, config, stack))


def estimate_full(repo: str, config: Config, stack: StackRule) -> int:
    return len(full_mod.build_full_units(repo, config, stack))

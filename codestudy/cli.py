"""CLI di CodeStudy (Typer)."""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import sys
from typing import List, Optional

import typer

from . import __version__
from .config import Config, load_config, example_yaml
from .providers.factory import build_provider
from .providers.base import ProviderError
from .runner import (
    estimate_full,
    estimate_incremental,
    run_full,
    run_incremental,
)
from .stack import detect_stack
from .state import StateStore
from .vcs import (
    GitError,
    changed_files,
    changed_files_in_commit,
    ensure_git_repo,
    resolve_commits,
    resolve_range,
    resolve_ref,
)

app = typer.Typer(
    add_completion=False,
    help="CodeStudy — flashcard, mappe e note dal tuo repo git per colmare il "
         "debito di comprensione del codice generato con l'AI.",
)


def _log(msg: str) -> None:
    typer.echo(msg)


def _err(msg: str) -> None:
    typer.echo(typer.style(msg, fg=typer.colors.RED), err=True)


def _run_id(mode: str, extra: str) -> str:
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    h = hashlib.sha1(extra.encode("utf-8")).hexdigest()[:6]
    return f"{mode}-{ts}-{h}"


def _confirm_cost(n_units: int, provider_name: str, assume_yes: bool) -> bool:
    typer.echo("")
    typer.echo(
        typer.style(
            f"Stima: circa {n_units} chiamate al provider '{provider_name}' "
            f"(1 chiamata per blocco).",
            fg=typer.colors.YELLOW,
        )
    )
    if n_units == 0:
        return False
    if assume_yes:
        typer.echo("--yes attivo: procedo senza chiedere conferma.")
        return True
    return typer.confirm("Procedo con l'analisi?", default=True)


@app.command()
def version() -> None:
    """Stampa la versione."""
    typer.echo(f"codestudy {__version__}")


@app.command("init-config")
def init_config(
    path: str = typer.Option("codestudy.yaml", "--path", "-o", help="File di config da creare."),
    force: bool = typer.Option(False, "--force", help="Sovrascrivi se esiste."),
) -> None:
    """Crea un file di configurazione di esempio commentato."""
    if os.path.exists(path) and not force:
        _err(f"'{path}' esiste gia'. Usa --force per sovrascrivere.")
        raise typer.Exit(code=1)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(example_yaml())
    _log(f"Config di esempio scritta in {path}")


def _prepare(repo: str, config_path: Optional[str], provider_override: Optional[str],
             output_override: Optional[str]):
    config = load_config(config_path)
    if provider_override:
        config.raw["provider"] = provider_override
    if output_override:
        config.raw["output_dir"] = output_override
    try:
        ensure_git_repo(repo)
    except GitError as e:
        _err(f"Errore git: {e}")
        raise typer.Exit(code=2)
    try:
        provider = build_provider(config)
    except ProviderError as e:
        _err(f"Errore provider: {e}")
        raise typer.Exit(code=2)
    return config, provider


@app.command()
def incremental(
    repo: str = typer.Option(".", "--repo", "-r", help="Percorso del repo git."),
    range_: Optional[str] = typer.Option(None, "--range", help="Range commit, es. HEAD~10..HEAD o <sha>..HEAD."),
    commit: Optional[List[str]] = typer.Option(
        None, "--commit", "-C",
        help="Analizza uno o piu' commit specifici (ripetibile). Ha precedenza su --range.",
    ),
    base: Optional[str] = typer.Option(
        None, "--base", "-b",
        help="Controllo pre-commit: analizza cio' che differisce da questo ref "
             "(branch/commit), incluse le modifiche NON committate. Es. --base main "
             "(il tuo branch vs main) o --base HEAD (solo il lavoro in sospeso).",
    ),
    config_path: Optional[str] = typer.Option("codestudy.yaml", "--config", "-c", help="File di config."),
    provider: Optional[str] = typer.Option(None, "--provider", help="Override del provider."),
    output: Optional[str] = typer.Option(None, "--output", help="Override cartella di output."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Salta la conferma dei costi."),
) -> None:
    """Modalita' incrementale: analizza il delta di commit.

    Selezione (in ordine di precedenza):
    - `--commit` : uno o piu' commit specifici (ognuno analizzato a se');
    - `--base`   : controllo pre-commit — cio' che differisce da un ref, incluse le
      modifiche non committate;
    - `--range`  : un range classico (default se non specifichi nient'altro).

    Le modifiche piccole ricevono una spiegazione minimale; quelle grandi il flusso
    completo.
    """
    cfg, prov = _prepare(repo, config_path, provider, output)

    commits = None
    commit_range = None
    sel_key = None
    sel_label = None
    if commit:
        try:
            commits = resolve_commits(repo, commit)
        except GitError as e:
            _err(f"Commit non validi: {e}")
            raise typer.Exit(code=2)
        files: list = []
        for sha in commits:
            files += changed_files_in_commit(repo, sha, cfg.path_filters)
        selection = "commit " + ", ".join(s[:8] for s in commits)
    elif base:
        try:
            commit_range = resolve_ref(repo, base)
        except GitError as e:
            _err(f"Ref di confronto non valido: {e}")
            raise typer.Exit(code=2)
        files = changed_files(repo, commit_range, cfg.path_filters)
        sel_key = "Confronto con"
        sel_label = commit_range
        selection = f"pre-commit vs {commit_range}"
        if not files:
            _log(f"Nessuna differenza rispetto a '{commit_range}' "
                 "(ricorda: i file nuovi vanno prima aggiunti con `git add`).")
    else:
        commit_range = range_ or cfg.commit_range
        try:
            commit_range = resolve_range(repo, commit_range)
        except GitError as e:
            _err(f"Range non valido: {e}")
            raise typer.Exit(code=2)
        files = changed_files(repo, commit_range, cfg.path_filters)
        selection = commit_range

    stack = detect_stack(repo, files)
    _log(f"Stack rilevato: {stack.name} (linguaggio: {stack.language})")

    n = estimate_incremental(repo, commit_range, cfg, stack, commits=commits)
    if not _confirm_cost(n, prov.name, yes):
        _log("Annullato.")
        raise typer.Exit(code=0)

    run_id = _run_id("incr", selection)
    out_dir = os.path.join(cfg.output_dir, run_id)
    store = StateStore(os.path.join(cfg.output_dir, "state.db"))
    store.start_run(run_id, "incremental", os.path.abspath(repo), selection, prov.name)
    try:
        paths = run_incremental(repo, commit_range, cfg, prov, store, run_id, out_dir,
                                stack, _log, commits=commits,
                                selection_key=sel_key, selection_label=sel_label)
    finally:
        store.close()
    _report(paths, out_dir)


@app.command()
def full(
    repo: str = typer.Option(".", "--repo", "-r", help="Percorso del repo git."),
    config_path: Optional[str] = typer.Option("codestudy.yaml", "--config", "-c", help="File di config."),
    provider: Optional[str] = typer.Option(None, "--provider", help="Override del provider."),
    output: Optional[str] = typer.Option(None, "--output", help="Override cartella di output."),
    module: Optional[str] = typer.Option(None, "--module", help="Limita a una sotto-cartella/modulo (prefisso path)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Salta la conferma dei costi."),
) -> None:
    """Modalita' intero software: mappatura gerarchica bottom-up."""
    cfg, prov = _prepare(repo, config_path, provider, output)
    if module:
        cfg.raw["path_filters"] = [module]

    stack = detect_stack(repo)
    _log(f"Stack rilevato: {stack.name} (linguaggio: {stack.language})")

    n = estimate_full(repo, cfg, stack)
    typer.echo(
        typer.style(
            "Nota: la modalita' intero software fa molte chiamate (una per file, "
            "una per modulo, una per l'architettura).",
            fg=typer.colors.YELLOW,
        )
    )
    if not _confirm_cost(n, prov.name, yes):
        _log("Annullato.")
        raise typer.Exit(code=0)

    run_id = _run_id("full", os.path.abspath(repo) + (module or ""))
    out_dir = os.path.join(cfg.output_dir, run_id)
    store = StateStore(os.path.join(cfg.output_dir, "state.db"))
    store.start_run(run_id, "full", os.path.abspath(repo), module or "(tutto)", prov.name)
    try:
        paths = run_full(repo, cfg, prov, store, run_id, out_dir, stack, _log)
    finally:
        store.close()
    _report(paths, out_dir)


def _report(paths, out_dir: str) -> None:
    typer.echo("")
    if not paths:
        _log("Nessun output prodotto.")
        return
    _log(typer.style(f"Fatto. Output in {out_dir}:", fg=typer.colors.GREEN))
    for p in paths:
        _log(f"  - {p}")


if __name__ == "__main__":
    app()

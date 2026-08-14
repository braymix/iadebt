"""Estrazione dati da un repository git locale (via subprocess `git`).

Nessuna dipendenza esterna: usa il `git` di sistema. Gestisce con chiarezza
i casi: git assente, non-repo, range vuoto/non valido.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import List, Optional


class GitError(RuntimeError):
    pass


def _run(repo: str, args: List[str]) -> str:
    if shutil.which("git") is None:
        raise GitError("`git` non e' installato o non e' nel PATH.")
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as e:
        raise GitError(f"Impossibile eseguire git: {e}") from e
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout or "errore git").strip())
    return proc.stdout


def ensure_git_repo(repo: str) -> None:
    if not os.path.isdir(repo):
        raise GitError(f"Percorso repo inesistente: {repo}")
    out = _run(repo, ["rev-parse", "--is-inside-work-tree"]).strip()
    if out != "true":
        raise GitError(f"'{repo}' non e' un repository git.")


def resolve_range(repo: str, commit_range: str) -> str:
    """Valida un range/revisione e la normalizza. Solleva se vuoto/non valido.

    Accetta forme come 'HEAD~10..HEAD', '<sha>..HEAD', o un singolo commit
    (interpretato come '<commit>..HEAD').
    """
    rng = (commit_range or "").strip()
    if not rng:
        raise GitError("Range di commit vuoto.")
    if ".." not in rng:
        rng = f"{rng}..HEAD"
    # verifica che entrambi gli estremi esistano
    left, right = rng.split("..", 1)
    for ref in (left or "HEAD", right or "HEAD"):
        try:
            _run(repo, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
        except GitError as e:
            raise GitError(f"Riferimento git non valido '{ref}': {e}") from e
    return rng


def resolve_commits(repo: str, commits: List[str]) -> List[str]:
    """Valida una lista di commit espliciti e la normalizza a SHA piene.

    Ogni voce puo' essere una qualsiasi revisione (sha corta, tag, `HEAD~2`, ...).
    Solleva se una voce non risolve a un commit. Rimuove i duplicati mantenendo
    l'ordine in cui sono stati indicati.
    """
    resolved: List[str] = []
    seen = set()
    for raw in commits:
        ref = (raw or "").strip()
        if not ref:
            continue
        try:
            sha = _run(repo, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]).strip()
        except GitError as e:
            raise GitError(f"Commit non valido '{ref}': {e}") from e
        if sha and sha not in seen:
            seen.add(sha)
            resolved.append(sha)
    if not resolved:
        raise GitError("Nessun commit valido specificato.")
    return resolved


def changed_files_in_commit(repo: str, sha: str,
                            path_filters: Optional[List[str]] = None) -> List[str]:
    """File modificati dal singolo commit (diff verso il primo parent).

    `--first-parent -m` fa mostrare, per i merge, cio' che il merge ha portato dal
    primo parent (altrimenti il diff combinato sarebbe vuoto); su un commit normale
    non cambia nulla. Gestisce anche il commit radice (confronto con l'albero vuoto).
    """
    args = ["diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent", sha]
    if path_filters:
        args += ["--", *path_filters]
    out = _run(repo, args)
    return [line.strip() for line in out.splitlines() if line.strip()]


def file_diff_in_commit(repo: str, sha: str, path: str) -> str:
    """Diff introdotto dal singolo commit per un file (senza header del commit)."""
    return _run(repo, ["show", "--format=", "-m", "--first-parent", sha, "--", path])


def resolve_ref(repo: str, ref: str) -> str:
    """Valida una singola revisione (branch/tag/commit) e la ritorna normalizzata.

    Usata per il confronto `git diff <ref>`, che mette a confronto quel ref con la
    working tree — quindi include anche le modifiche NON ancora committate.
    """
    r = (ref or "").strip()
    if not r:
        raise GitError("Riferimento vuoto.")
    try:
        _run(repo, ["rev-parse", "--verify", "--quiet", f"{r}^{{commit}}"])
    except GitError as e:
        raise GitError(f"Riferimento git non valido '{r}': {e}") from e
    return r


def changed_files(repo: str, commit_range: str, path_filters: Optional[List[str]] = None) -> List[str]:
    """File modificati nel range (relativi alla root del repo)."""
    args = ["diff", "--name-only", commit_range]
    if path_filters:
        args += ["--", *path_filters]
    out = _run(repo, args)
    files = [line.strip() for line in out.splitlines() if line.strip()]
    return files


def file_diff(repo: str, commit_range: str, path: str) -> str:
    """Diff aggregato del singolo file sul range."""
    return _run(repo, ["diff", commit_range, "--", path])


def list_tracked_files(repo: str, path_filters: Optional[List[str]] = None) -> List[str]:
    """Tutti i file tracciati (per la modalita' intero software)."""
    args = ["ls-files"]
    if path_filters:
        args += ["--", *path_filters]
    out = _run(repo, args)
    return [line.strip() for line in out.splitlines() if line.strip()]


def read_file_at_head(repo: str, path: str) -> str:
    """Contenuto del file a HEAD. Ritorna '' se binario/non leggibile."""
    try:
        return _run(repo, ["show", f"HEAD:{path}"])
    except GitError:
        return ""

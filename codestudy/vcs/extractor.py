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

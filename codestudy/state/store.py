"""Stato di ripresa in SQLite.

Unita' = una chiamata AI. Un'unita' completata non viene rieseguita: cosi' un
run su molti commit o sull'intero software puo' riprendere da dove era rimasto.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

from ..models import AnalysisResult


class StateStore:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init()

    def _init(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id     TEXT PRIMARY KEY,
                    mode       TEXT,
                    repo       TEXT,
                    commit_range TEXT,
                    provider   TEXT,
                    created_at REAL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS units (
                    run_id     TEXT,
                    unit_key   TEXT,
                    kind       TEXT,
                    title      TEXT,
                    status     TEXT,        -- pending | done | error
                    result_json TEXT,
                    error      TEXT,
                    updated_at REAL,
                    PRIMARY KEY (run_id, unit_key)
                )
                """
            )

    # ---- runs ----
    def start_run(self, run_id: str, mode: str, repo: str, commit_range: str,
                  provider: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?,?)",
                (run_id, mode, repo, commit_range, provider, time.time()),
            )

    # ---- units ----
    def is_done(self, run_id: str, unit_key: str) -> bool:
        cur = self._conn.execute(
            "SELECT status FROM units WHERE run_id=? AND unit_key=?",
            (run_id, unit_key),
        )
        row = cur.fetchone()
        return bool(row and row[0] == "done")

    def get_result(self, run_id: str, unit_key: str) -> Optional[AnalysisResult]:
        cur = self._conn.execute(
            "SELECT result_json FROM units WHERE run_id=? AND unit_key=? AND status='done'",
            (run_id, unit_key),
        )
        row = cur.fetchone()
        if row and row[0]:
            return AnalysisResult.from_json(row[0])
        return None

    def get_results_by_kind(self, run_id: str, kind: str) -> Dict[str, AnalysisResult]:
        cur = self._conn.execute(
            "SELECT unit_key, result_json FROM units "
            "WHERE run_id=? AND kind=? AND status='done'",
            (run_id, kind),
        )
        out: Dict[str, AnalysisResult] = {}
        for key, rj in cur.fetchall():
            if rj:
                out[key] = AnalysisResult.from_json(rj)
        return out

    def save_done(self, run_id: str, unit_key: str, kind: str, title: str,
                  result: AnalysisResult) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO units VALUES (?,?,?,?,?,?,?,?)",
                (run_id, unit_key, kind, title, "done",
                 result.to_json(), None, time.time()),
            )

    def save_error(self, run_id: str, unit_key: str, kind: str, title: str,
                   error: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO units VALUES (?,?,?,?,?,?,?,?)",
                (run_id, unit_key, kind, title, "error", None, error[:2000], time.time()),
            )

    def counts(self, run_id: str) -> Dict[str, int]:
        cur = self._conn.execute(
            "SELECT status, COUNT(*) FROM units WHERE run_id=? GROUP BY status",
            (run_id,),
        )
        return {status: n for status, n in cur.fetchall()}

    def close(self) -> None:
        self._conn.close()

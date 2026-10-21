import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path


class Ledger:
    """사용량을 호출 전에 기록하여 재개 시 예산을 복원합니다."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, started REAL NOT NULL, turns INTEGER NOT NULL DEFAULT 0,
                tokens INTEGER NOT NULL DEFAULT 0, tools TEXT NOT NULL DEFAULT '{}',
                report TEXT, result TEXT, fingerprint TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lookups (run_id TEXT NOT NULL, cache_key TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(run_id,cache_key));
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL, at REAL NOT NULL);
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(runs)")}
        if "input_key" not in columns:
            self.db.execute("ALTER TABLE runs ADD COLUMN input_key TEXT NOT NULL DEFAULT ''")
        self.db.execute("CREATE INDEX IF NOT EXISTS runs_input_key ON runs(input_key)")
        self.db.commit()
        os.chmod(path, 0o600)
        self.lock = asyncio.Lock()

    def begin(self, task_id: str, fingerprint: str, input_key: str = "") -> None:
        if input_key:
            for row in self.db.execute(
                "SELECT result FROM runs WHERE input_key=? AND id<>?", (input_key, task_id)
            ):
                if row[0] is None or json.loads(row[0]).get("status") == "SAVE_FAILED":
                    raise ValueError(
                        "동일한 입력의 분석이 진행 중이거나 재저장을 기다리고 있습니다."
                    )
        self.db.execute(
            "INSERT OR IGNORE INTO runs(id,started,fingerprint,input_key) VALUES(?,?,?,?)",
            (task_id, time.time(), fingerprint, input_key),
        )
        self.db.commit()
        if self.row(task_id)["fingerprint"] != fingerprint:
            raise ValueError("작업 ID와 고정 입력이 일치하지 않습니다.")

    def row(self, task_id: str) -> dict:
        self.db.row_factory = sqlite3.Row
        return dict(self.db.execute("SELECT * FROM runs WHERE id=?", (task_id,)).fetchone())

    def event(self, task_id: str, kind: str, **payload) -> None:
        self.db.execute(
            "INSERT INTO events(run_id,kind,payload,at) VALUES(?,?,?,?)",
            (task_id, kind, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        self.db.commit()

    def events(self, task_id: str, after: int = 0) -> list[dict]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT id,kind,payload,at FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT 100",
                (task_id, after),
            )
        ]

    def keep(self, task_id: str, key: str, value: dict) -> None:
        if key not in {"report", "result"}:
            raise ValueError("잘못된 보존 항목입니다.")
        self.db.execute(
            f"UPDATE runs SET {key}=? WHERE id=?", (json.dumps(value, ensure_ascii=False), task_id)
        )
        self.db.commit()

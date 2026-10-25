"""SQLite persistence; separate connections make concurrent requests safe."""
import json
import os
from pathlib import Path
import sqlite3


def connect():
    path = Path(os.environ.get("DRIFT_DB", ".runtime/drift.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db():
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")


def save(kind, data):
    if kind not in ("runs", "batches"):
        raise ValueError("Invalid storage kind")
    with connect() as db:
        db.execute(f"INSERT OR REPLACE INTO {kind} VALUES (?, ?, ?)", (data["id"], data["created_at"], json.dumps(data, allow_nan=False)))


def get(kind, identity):
    if kind not in ("runs", "batches"):
        raise ValueError("Invalid storage kind")
    with connect() as db:
        row = db.execute(f"SELECT payload FROM {kind} WHERE id = ?", (identity,)).fetchone()
    return json.loads(row[0]) if row else None


def list_records(kind, limit=200):
    if kind not in ("runs", "batches"):
        raise ValueError("Invalid storage kind")
    with connect() as db:
        rows = db.execute(f"SELECT payload FROM {kind} ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def interrupt_batches():
    for batch in list_records("batches", 10000):
        if batch["status"] in ("queued", "running"):
            batch.update(status="interrupted", error="Server restarted before this benchmark finished.")
            save("batches", batch)

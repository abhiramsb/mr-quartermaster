"""Tiny per-server key/value store (SQLite)."""
from __future__ import annotations

import sqlite3
import threading
from typing import Optional


class Settings:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS settings ("
            "guild_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "PRIMARY KEY (guild_id, key))"
        )
        self._db.commit()

    def get(self, guild_id: int, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM settings WHERE guild_id=? AND key=?", (guild_id, key)
            ).fetchone()
        return row[0] if row else default

    def get_int(self, guild_id: int, key: str) -> Optional[int]:
        value = self.get(guild_id, key)
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    def set(self, guild_id: int, key: str, value) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO settings (guild_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
                (guild_id, key, str(value)),
            )
            self._db.commit()

    def delete(self, guild_id: int, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM settings WHERE guild_id=? AND key=?", (guild_id, key))
            self._db.commit()

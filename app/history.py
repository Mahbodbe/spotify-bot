"""Tiny sqlite store: download history (file_id cache), user prefs, stats."""
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    track_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    artists TEXT NOT NULL DEFAULT '',
    file_id TEXT NOT NULL,
    quality INTEGER NOT NULL DEFAULT 192,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dl_user_track
    ON downloads(user_id, track_id);
CREATE TABLE IF NOT EXISTS prefs (
    user_id INTEGER PRIMARY KEY,
    quality INTEGER NOT NULL DEFAULT 192
);
"""


class History:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.executescript(SCHEMA)

    def _connect(self):
        return sqlite3.connect(self.path)

    # -- file_id cache --
    def get_cached(self, user_id, track_id):
        with self._connect() as c:
            row = c.execute(
                "SELECT file_id, title, artists, quality FROM downloads"
                " WHERE user_id=? AND track_id=?",
                (user_id, track_id),
            ).fetchone()
        if not row:
            return None
        return {"file_id": row[0], "title": row[1],
                "artists": row[2], "quality": row[3]}

    def save(self, user_id, track_id, title, artists, file_id,
             quality, size_bytes):
        with self._connect() as c:
            c.execute(
                "INSERT INTO downloads(user_id, track_id, title, artists,"
                " file_id, quality, size_bytes, created_at)"
                " VALUES(?,?,?,?,?,?,?,?)"
                " ON CONFLICT(user_id, track_id) DO UPDATE SET"
                " file_id=excluded.file_id, quality=excluded.quality,"
                " size_bytes=excluded.size_bytes,"
                " created_at=excluded.created_at",
                (user_id, track_id, title, artists, file_id,
                 quality, size_bytes, int(time.time())),
            )

    # -- prefs --
    def get_quality(self, user_id, default=192):
        with self._connect() as c:
            row = c.execute(
                "SELECT quality FROM prefs WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return row[0] if row else default

    def set_quality(self, user_id, quality):
        with self._connect() as c:
            c.execute(
                "INSERT INTO prefs(user_id, quality) VALUES(?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET quality=excluded.quality",
                (user_id, quality),
            )

    # -- stats --
    def stats(self, user_id):
        with self._connect() as c:
            row = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM downloads"
                " WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return {"count": row[0], "bytes": row[1]}

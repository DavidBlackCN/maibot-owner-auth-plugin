from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
import threading
import secrets
import uuid

from ..shared.core import Denied, opaque, require


class WriterLease:
    """OS advisory lock; the persistent file is never unlinked while held."""
    def __init__(self, path: Path):
        self.path, self.handle = path, None

    def acquire(self):
        require(self.handle is None, "WRITER_LOCKED")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            handle.close()
            raise Denied("WRITER_LOCKED")
        self.handle = handle

    def release(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


SCHEMA = "CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);"


class Database:
    def __init__(self, path: Path, *, create: bool = False):
        self.path = Path(path)
        self.guard = threading.RLock()
        self.conn = None
        exists = self.path.exists()
        require(exists or create, "STORAGE_UNAVAILABLE")
        if create:
            require(not exists, "TARGET_EXISTS")
        try:
            self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=2)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys=ON")
            if create:
                self.conn.executescript("BEGIN IMMEDIATE;" + SCHEMA + "PRAGMA user_version=1; COMMIT;")
            require(self.conn.execute("PRAGMA user_version").fetchone()[0] == 1, "UNKNOWN_SCHEMA")
            require(self.conn.execute("PRAGMA quick_check").fetchone()[0] == "ok", "STORAGE_UNAVAILABLE")
            self.conn.execute("SELECT key,value FROM metadata").fetchall()
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self):
        with self.guard:
            require(self.conn is not None, "STORAGE_UNAVAILABLE")
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def context_state(self):
        # Only metadata is used. Unrelated existing tables/records are untouched.
        with self.transaction():
            values = {}
            for name in ("deployment_instance_id", "context_ownership_key"):
                row = self.conn.execute("SELECT value FROM metadata WHERE key=?", (name,)).fetchone()
                value = row[0] if row else ("maiidentity-" + uuid.uuid4().hex if name == "deployment_instance_id" else secrets.token_hex(32))
                if row is None:
                    self.conn.execute("INSERT INTO metadata VALUES(?,?)", (name, value))
                values[name] = value
            instance = opaque(values["deployment_instance_id"])
            key = bytes.fromhex(values["context_ownership_key"])
            require(len(key) == 32, "STORAGE_UNAVAILABLE")
            return instance, key

    def close(self):
        with self.guard:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

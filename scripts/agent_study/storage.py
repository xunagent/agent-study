"""Small local recovery journal; cloud documents remain the durable source."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

from .model import StudyError


class Local:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "recovery.json"

    def read(self):
        if not self.path.exists():
            return {"pending": {}, "binding": None}
        return json.loads(self.path.read_text())

    def write(self, value):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temporary.chmod(0o600)
        os.replace(temporary, self.path)

    def binding(self, value=None):
        state = self.read()
        if value is not None:
            state["binding"] = value
            self.write(state)
        return state["binding"]

    def pending(self, key, value=None):
        state = self.read()
        if value is not None:
            state["pending"][key] = value
            self.write(state)
        return state["pending"].get(key)

    @contextmanager
    def lock(self):
        # Advisory locks are released by the OS after crashes; no stale PID files.
        handle = (self.directory / "run.lock").open("a+b")
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise StudyError("Another local Agent Study operation is running") from exc
        try:
            yield
        finally:
            handle.close()

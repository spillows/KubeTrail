"""Keep the quest progress in progress.json in the repo root.

The file has the time at which the user completed each quest. Git ignores
the file. Each write goes to a temporary file first. Then os.replace puts it
in place in one operation. Thus, a crash cannot leave half a file.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "progress.json"
VERSION = 1

QUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# FastAPI runs the routes in a thread pool. The lock stops two requests that
# write the file at the same time.
_lock = threading.Lock()


class ProgressError(ValueError):
    """The request is not valid. For example, the quest id is not valid."""


class ProgressFileError(RuntimeError):
    """progress.json is not valid. The app does not write over it."""


def _path(path: Path | None) -> Path:
    return path if path is not None else PATH


def _check_id(quest_id: str) -> None:
    if not QUEST_ID_RE.match(quest_id):
        raise ProgressError(f"The quest id '{quest_id}' is not valid.")


def _read(path: Path) -> dict:
    if not path.exists():
        return {"version": VERSION, "done": {}}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ProgressFileError(f"{path.name} is not valid JSON ({e}). Repair the file or move it away.") from None
    done = data.get("done") if isinstance(data, dict) else None
    if not isinstance(done, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in done.items()):
        raise ProgressFileError(f"{path.name} does not have the expected format. Repair the file or move it away.")
    return data


def _write(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _view(data: dict) -> dict:
    return {"done": dict(data["done"])}


def load(path: Path | None = None) -> dict:
    """Return the progress as {"done": {quest_id: time}}."""
    with _lock:
        return _view(_read(_path(path)))


def mark(quest_id: str, path: Path | None = None) -> dict:
    """Record a quest as done. Keep the first time if the quest is already done."""
    _check_id(quest_id)
    p = _path(path)
    with _lock:
        data = _read(p)
        if quest_id not in data["done"]:
            data["done"][quest_id] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _write(p, data)
        return _view(data)


def unmark(quest_id: str, path: Path | None = None) -> dict:
    """Remove the done record of a quest. Do nothing if the quest is not done."""
    _check_id(quest_id)
    p = _path(path)
    with _lock:
        data = _read(p)
        if data["done"].pop(quest_id, None) is not None:
            _write(p, data)
        return _view(data)

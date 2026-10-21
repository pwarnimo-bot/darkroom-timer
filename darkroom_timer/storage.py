"""Persistence: development log, user presets and last-used setup (JSON files)."""

from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path

from .models import Session


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    path = Path(base) / "darkroom-timer"
    path.mkdir(parents=True, exist_ok=True)
    return path


LOG_FILE = "log.json"
USER_PRESETS_FILE = "presets.json"
LAST_SETUP_FILE = "last_setup.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        # Keep the broken file around rather than silently overwriting it.
        path.rename(path.with_suffix(path.suffix + ".corrupt"))
        return default


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# --- Log -------------------------------------------------------------------

def load_log() -> list[Session]:
    return [Session.from_dict(d) for d in _read_json(data_dir() / LOG_FILE, [])]


def save_log(sessions: list[Session]) -> None:
    _write_json(data_dir() / LOG_FILE, [s.to_dict() for s in sessions])


def append_log(session: Session) -> None:
    sessions = load_log()
    sessions.append(session)
    save_log(sessions)


def update_log_entry(session: Session) -> None:
    """Replace the entry with the same start time (used to edit notes later)."""
    sessions = load_log()
    for i, s in enumerate(sessions):
        if s.started_at == session.started_at:
            sessions[i] = session
            break
    else:
        sessions.append(session)
    save_log(sessions)


def delete_log_entry(started_at: str) -> None:
    save_log([s for s in load_log() if s.started_at != started_at])


# --- Presets ---------------------------------------------------------------

def load_presets() -> list[dict]:
    """Bundled datasheet presets followed by the user's own presets."""
    bundled = json.loads(
        resources.files("darkroom_timer").joinpath("presets.json").read_text(encoding="utf-8")
    )["presets"]
    for p in bundled:
        p["source"] = p.get("source", "datasheet")
    user = _read_json(data_dir() / USER_PRESETS_FILE, [])
    for p in user:
        p["source"] = "mine"
    return bundled + user


def save_user_preset(preset: dict) -> None:
    path = data_dir() / USER_PRESETS_FILE
    presets = _read_json(path, [])
    key = (preset["film"], preset.get("ei"), preset["developer"], preset.get("dilution"))
    presets = [
        p for p in presets
        if (p["film"], p.get("ei"), p["developer"], p.get("dilution")) != key
    ]
    presets.append({k: v for k, v in preset.items() if k != "source"})
    _write_json(path, presets)


# --- Last setup ------------------------------------------------------------

def load_last_setup() -> dict:
    return _read_json(data_dir() / LAST_SETUP_FILE, {})


def save_last_setup(setup: dict) -> None:
    _write_json(data_dir() / LAST_SETUP_FILE, setup)

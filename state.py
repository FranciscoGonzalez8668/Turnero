import json
import logging
from datetime import datetime
from pathlib import Path


STATE_PATH = Path("state.json")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception as err:  # noqa: BLE001
        logging.warning("No se pudo parsear fecha de estado (%s): %s", value, err)
        return None


def load_state() -> dict[str, datetime | None]:
    if not STATE_PATH.exists():
        return {"blocked_until": None, "last_run": None}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as err:  # noqa: BLE001
        logging.warning("No se pudo leer state.json: %s", err)
        return {"blocked_until": None, "last_run": None}
    return {
        "blocked_until": _parse_dt(data.get("blocked_until")),
        "last_run": _parse_dt(data.get("last_run")),
    }


def save_state(blocked_until: datetime | None, last_run: datetime | None):
    payload = {
        "blocked_until": blocked_until.isoformat() if blocked_until else None,
        "last_run": last_run.isoformat() if last_run else None,
    }
    try:
        STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as err:  # noqa: BLE001
        logging.warning("No se pudo guardar state.json: %s", err)

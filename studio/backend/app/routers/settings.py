import json
from fastapi import APIRouter

from .. import database as db
from ..schemas import SettingUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings():
    with db.db_session() as conn:
        rows = conn.execute("SELECT * FROM settings").fetchall()
        out = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["value"])
            except Exception:
                out[r["key"]] = r["value"]
        return out


@router.put("")
def set_setting(payload: SettingUpdate):
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (payload.key, json.dumps(payload.value)),
        )
    return {"key": payload.key, "value": payload.value}

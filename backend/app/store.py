"""A small SQLite store: patients, text messages, alerts for the care team, daily weights, and medicine adherence.

One file on disk (MEDBRIDGE_DB, default backend/data/medbridge.sqlite3), nothing to install.

NOT for real patient data: the file is not encrypted and the API has no login yet. See docs/phase-4.md.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "medbridge.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
  id TEXT PRIMARY KEY, name TEXT, phone TEXT, mode TEXT NOT NULL, consent INTEGER NOT NULL DEFAULT 0,
  opted_out INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  sim_day INTEGER NOT NULL DEFAULT 0, sim_cursor INTEGER NOT NULL DEFAULT 0,
  awaiting TEXT NOT NULL DEFAULT '', language TEXT NOT NULL DEFAULT 'en', extraction TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT '', last_event TEXT NOT NULL DEFAULT '',
  chat_id TEXT NOT NULL DEFAULT '', link_token TEXT NOT NULL DEFAULT '', linked_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, direction TEXT NOT NULL, body TEXT NOT NULL,
  kind TEXT NOT NULL, sim_label TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, delivery TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, level TEXT NOT NULL, title TEXT NOT NULL,
  detail TEXT NOT NULL, rule_id TEXT NOT NULL, day INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  acknowledged INTEGER NOT NULL DEFAULT 0, acknowledged_at TEXT, ack_note TEXT NOT NULL DEFAULT '', ack_by TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS weights (
  patient_id TEXT NOT NULL, day INTEGER NOT NULL, pounds REAL NOT NULL, PRIMARY KEY (patient_id, day)
);
CREATE TABLE IF NOT EXISTS adherence (
  patient_id TEXT NOT NULL, day INTEGER NOT NULL, slot TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (patient_id, day, slot)
);
CREATE INDEX IF NOT EXISTS idx_messages_patient ON messages (patient_id, id);
CREATE INDEX IF NOT EXISTS idx_alerts_patient ON alerts (patient_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    return Path(os.environ.get("MEDBRIDGE_DB") or DEFAULT_PATH)


class Store:
    def __init__(self, path: Path | str | None = None, clock: Callable[[], str] | None = None):
        self.path = Path(path) if path else db_path()
        self.clock = clock or _now          # tests and the demo data can supply their own time
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._conn()
        try:
            with conn:
                conn.executescript(SCHEMA)
                # A database made by an earlier phase has no acknowledgement columns: add them, keep the rows.
                have = {r["name"] for r in conn.execute("PRAGMA table_info(alerts)")}
                for col, ddl in (("acknowledged_at", "TEXT"), ("ack_note", "TEXT NOT NULL DEFAULT ''"), ("ack_by", "TEXT NOT NULL DEFAULT ''")):
                    if col not in have:
                        conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} {ddl}")
                if "delivery" not in {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}:
                    conn.execute("ALTER TABLE messages ADD COLUMN delivery TEXT NOT NULL DEFAULT ''")
                have = {r["name"] for r in conn.execute("PRAGMA table_info(patients)")}
                for col in ("timezone", "last_event", "chat_id", "link_token", "linked_at"):
                    if col not in have:
                        conn.execute(f"ALTER TABLE patients ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        finally:
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _run(self, sql: str, args: tuple = ()) -> int:
        conn = self._conn()
        try:
            with conn:
                cur = conn.execute(sql, args)
                return cur.lastrowid or 0
        finally:
            conn.close()

    def _all(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()

    # ---- patients -----------------------------------------------------
    def create_patient(self, *, name: str | None, phone: str | None, mode: str, consent: bool, language: str, extraction_json: str,
                       pid: str | None = None, timezone: str = "", link_token: str = "") -> str:
        pid = pid or uuid.uuid4().hex[:12]
        self._run("INSERT INTO patients (id, name, phone, mode, consent, created_at, language, extraction, timezone, link_token) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (pid, name, phone, mode, int(consent), self.clock(), language, extraction_json, timezone, link_token))
        return pid

    def get_patient(self, pid: str) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM patients WHERE id = ?", (pid,))
        return rows[0] if rows else None

    def find_by_link_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        rows = self._all("SELECT * FROM patients WHERE link_token = ? AND mode = 'telegram' AND chat_id = ''", (token,))
        return rows[0] if rows else None

    def find_by_chat(self, chat_id: str) -> dict[str, Any] | None:
        if not chat_id:
            return None
        rows = self._all("SELECT * FROM patients WHERE chat_id = ? AND mode = 'telegram' ORDER BY linked_at DESC, created_at DESC LIMIT 1", (chat_id,))
        return rows[0] if rows else None

    def link_telegram(self, pid: str, chat_id: str) -> None:
        """The patient tapped Start in Telegram: remember the chat, count that as agreeing to messages, and retire the one-time link."""
        self._run("UPDATE patients SET chat_id = ?, consent = 1, linked_at = ?, link_token = '' WHERE id = ?", (chat_id, self.clock(), pid))

    def get_kv(self, key: str, default: str = "") -> str:
        rows = self._all("SELECT value FROM kv WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def set_kv(self, key: str, value: str) -> None:
        self._run("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def all_patients(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM patients ORDER BY created_at, id")

    def delete_patients(self, id_prefix: str) -> int:
        """Removes every patient whose id starts with ``id_prefix`` and everything stored about them (used for the example patients)."""
        ids = [r["id"] for r in self._all("SELECT id FROM patients WHERE id LIKE ?", (id_prefix.replace("%", "") + "%",))]
        for table in ("messages", "alerts", "weights", "adherence"):
            for pid in ids:
                self._run(f"DELETE FROM {table} WHERE patient_id = ?", (pid,))
        for pid in ids:
            self._run("DELETE FROM patients WHERE id = ?", (pid,))
        return len(ids)

    def find_by_phone(self, phone: str) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM patients WHERE phone = ? AND mode = 'sms' ORDER BY created_at DESC LIMIT 1", (phone,))
        return rows[0] if rows else None

    def update_patient(self, pid: str, **fields: Any) -> None:
        allowed = {"opted_out", "sim_day", "sim_cursor", "awaiting", "last_event"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"cannot update {bad}")
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._run(f"UPDATE patients SET {cols} WHERE id = ?", (*fields.values(), pid))

    # ---- messages -------------------------------------------------------
    def add_message(self, pid: str, direction: str, body: str, kind: str, sim_label: str = "") -> int:
        return self._run("INSERT INTO messages (patient_id, direction, body, kind, sim_label, created_at) VALUES (?,?,?,?,?,?)",
                         (pid, direction, body, kind, sim_label, self.clock()))

    def last_messages(self, pid: str) -> dict[str, dict[str, Any] | None]:
        """The newest text in each direction, so the dashboard can show 'last heard from the patient'."""
        out: dict[str, dict[str, Any] | None] = {}
        for direction in ("in", "out"):
            rows = self._all("SELECT direction, body, kind, sim_label, created_at FROM messages WHERE patient_id = ? AND direction = ? "
                             "ORDER BY id DESC LIMIT 1", (pid, direction))
            out[direction] = rows[0] if rows else None
        return out

    def mark_delivery(self, message_id: int, status: str) -> None:
        """'' = no problem known, 'failed' = the phone company or Twilio refused it."""
        self._run("UPDATE messages SET delivery = ? WHERE id = ?", (status, message_id))

    def messages(self, pid: str) -> list[dict[str, Any]]:
        return self._all("SELECT id, direction, body, kind, sim_label, created_at, delivery FROM messages WHERE patient_id = ? ORDER BY id", (pid,))

    # ---- alerts ----------------------------------------------------------
    def add_alert(self, pid: str, level: str, title: str, detail: str, rule_id: str, day: int) -> int | None:
        """Adds an alert unless the same rule already raised an open one on the same day (so one worry is not repeated)."""
        ongoing = rule_id in ("adherence", "delivery_failed")  # one open alert per ongoing problem, whatever the day
        dup = self._all(f"SELECT id FROM alerts WHERE patient_id = ? AND rule_id = ? AND acknowledged = 0{'' if ongoing else ' AND day = ?'}",
                        (pid, rule_id) if ongoing else (pid, rule_id, day))
        if dup:
            return None
        return self._run("INSERT INTO alerts (patient_id, level, title, detail, rule_id, day, created_at) VALUES (?,?,?,?,?,?,?)",
                         (pid, level, title, detail, rule_id, day, self.clock()))

    _ALERT_COLS = "id, patient_id, level, title, detail, rule_id, day, created_at, acknowledged, acknowledged_at, ack_note, ack_by"

    def alerts(self, pid: str) -> list[dict[str, Any]]:
        return self._all(f"SELECT {self._ALERT_COLS} FROM alerts WHERE patient_id = ? "
                         "ORDER BY acknowledged, CASE level WHEN 'urgent' THEN 0 WHEN 'same_day' THEN 1 ELSE 2 END, id DESC", (pid,))

    def all_alerts(self) -> list[dict[str, Any]]:
        return self._all(f"SELECT {self._ALERT_COLS} FROM alerts ORDER BY id")

    def acknowledge(self, alert_id: int, note: str = "", by: str = "") -> bool:
        """Marks an alert as seen, remembering who and when. A second click never overwrites the first person's note."""
        conn = self._conn()
        try:
            with conn:
                if conn.execute("SELECT 1 FROM alerts WHERE id = ?", (alert_id,)).fetchone() is None:
                    return False
                conn.execute("UPDATE alerts SET acknowledged = 1, acknowledged_at = ?, ack_note = ?, ack_by = ? "
                             "WHERE id = ? AND acknowledged = 0", (self.clock(), note.strip()[:500], by.strip()[:80], alert_id))
                return True
        finally:
            conn.close()

    # ---- weights / adherence ---------------------------------------------
    def set_weight(self, pid: str, day: int, pounds: float) -> None:
        self._run("INSERT INTO weights (patient_id, day, pounds) VALUES (?,?,?) ON CONFLICT(patient_id, day) DO UPDATE SET pounds = excluded.pounds",
                  (pid, day, pounds))

    def weights(self, pid: str) -> dict[int, float]:
        return {r["day"]: r["pounds"] for r in self._all("SELECT day, pounds FROM weights WHERE patient_id = ? ORDER BY day", (pid,))}

    def set_adherence(self, pid: str, day: int, slot: str, status: str) -> None:
        self._run("INSERT INTO adherence (patient_id, day, slot, status) VALUES (?,?,?,?) ON CONFLICT(patient_id, day, slot) DO UPDATE SET status = excluded.status",
                  (pid, day, slot, status))

    def adherence(self, pid: str) -> list[dict[str, Any]]:
        return self._all("SELECT day, slot, status FROM adherence WHERE patient_id = ? ORDER BY day, slot", (pid,))


def dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)

"""The care-team view across ALL patients: who needs a call first, and what has already been handled.

Everything here is plain code over what the check-ins stored (alerts, weights, adherence). No AI, no guessing.
"No open alerts" means exactly that. A patient who turned texts off is shown as "Texts stopped" (nobody is watching them any more),
and a patient who stops answering reminders gets a "missed medicines" alert from the check-in engine, so silence is not hidden.
"""

from datetime import datetime, timezone
from statistics import median
from typing import Any

from . import redflags as rf
from .checkins import CheckInEngine
from .schemas import ExtractionResult
from .store import Store

# Highest first. "stopped" = the patient turned texts off: nobody is watching them any more, so a person should call.
STATUS_RANK = {"emergency": 0, "call_today": 1, "review": 2, "stopped": 3, "ok": 4}
STATUS_LABEL = {"emergency": "Emergency", "call_today": "Call today", "review": "Please read", "stopped": "Texts stopped", "ok": "No open alerts"}
LEVEL_STATUS = {rf.URGENT: "emergency", rf.SAME_DAY: "call_today", rf.REVIEW: "review"}
LEVEL_ORDER = {rf.URGENT: 0, rf.SAME_DAY: 1, rf.REVIEW: 2}


def _level_rank(alert: dict[str, Any]) -> int:
    return LEVEL_ORDER.get(alert["level"], 9)

SEEN_ALERTS_SHOWN = 25
TREND_POINTS = 7

# Fixed, operational suggestions. They never say what is medically wrong or what to prescribe: that belongs to the clinic's own protocol.
NEXT_STEP_BY_RULE = {
    "adherence": "Call to ask why the medicines were missed (cost, side effects, confusion, or no supply left).",
    "ran_out": "Arrange a refill, then call to confirm the patient has the medicine.",
    "delivery_failed": "Texts are not reaching this patient. Contact them another way.",
    "review": "Read the message and decide whether to call.",
}
NEXT_STEP_BY_LEVEL = {
    rf.URGENT: "Call the patient now. If there is no answer, follow your clinic's emergency protocol.",
    rf.SAME_DAY: "Call the patient today.",
    rf.REVIEW: "Read the message and decide whether to call.",
}


def next_step(level: str, rule_id: str) -> str:
    return NEXT_STEP_BY_RULE.get(rule_id) or NEXT_STEP_BY_LEVEL.get(level, "")


def _when(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def _display_name(p: dict[str, Any]) -> str:
    return (p["name"] or "").strip() or f"Patient {p['id'][:4]}"


def headline(level: str, rule_id: str, title: str) -> str:
    """A short heading for lists. Paper signs can be long sentences, so use the symptom's short name when there is one."""
    concept = rf.BY_ID.get(rule_id.split(":")[-1])
    if concept and rule_id.startswith(("paper", "universal")):
        return f"{'Emergency' if level == rf.URGENT else 'Warning sign'}: {concept.label}"
    return title


def _alert_row(a: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    return {
        "id": a["id"], "patient_id": a["patient_id"], "patient_name": names.get(a["patient_id"], "Unknown patient"),
        "level": a["level"], "title": headline(a["level"], a["rule_id"], a["title"]), "detail": a["detail"], "day": a["day"] + 1, "created_at": a["created_at"],
        "acknowledged": bool(a["acknowledged"]), "acknowledged_at": a["acknowledged_at"], "note": a["ack_note"], "by": a["ack_by"],
        "next_step": next_step(a["level"], a["rule_id"]),
    }


def _patient_row(store: Store, p: dict[str, Any], alerts: list[dict[str, Any]]) -> dict[str, Any]:
    pid = p["id"]
    try:
        ex: ExtractionResult | None = CheckInEngine.extraction(p)
    except ValueError:                       # a damaged record must not take the whole dashboard down
        ex = None
    open_alerts = [a for a in alerts if not a["acknowledged"]]
    open_alerts.sort(key=lambda a: (_level_rank(a), a["created_at"], a["id"]))
    if open_alerts:
        top = open_alerts[0]["level"]
        status = LEVEL_STATUS.get(top, "review")
    elif p["opted_out"]:
        status = "stopped"
    else:
        status = "ok"
    oldest_top = open_alerts[0]["created_at"] if open_alerts else None   # sorted: worst level, then oldest

    weights = sorted(store.weights(pid).items())
    adherence = store.adherence(pid)
    counts = {s: sum(a["status"] == s for a in adherence) for s in ("taken", "missed", "unanswered")}
    total = sum(counts.values())
    last = store.last_messages(pid)
    return {
        "id": pid,
        "name": _display_name(p),
        "mode": p["mode"],
        "day": p["sim_day"] + 1,
        "diagnosis": ex.diagnosis_summary if ex else None,
        "medicine_count": sum(1 for m in ex.medications if m.status != "stop") if ex else 0,
        "status": status,
        "status_label": STATUS_LABEL[status],
        "opted_out": bool(p["opted_out"]),
        "connected": p["mode"] != "telegram" or bool(p["chat_id"]),     # a Telegram patient who never pressed Start cannot be reached
        "open_alerts": len(open_alerts),
        "open_by_level": {lv: sum(a["level"] == lv for a in open_alerts) for lv in (rf.URGENT, rf.SAME_DAY, rf.REVIEW)},
        "top_alert": headline(open_alerts[0]["level"], open_alerts[0]["rule_id"], open_alerts[0]["title"]) if open_alerts else None,
        "waiting_since": oldest_top,
        "weight": ({"latest": weights[-1][1], "change": round(weights[-1][1] - weights[0][1], 1), "trend": [w for _, w in weights[-TREND_POINTS:]]}
                   if weights else None),
        "adherence": {**counts, "rate": round(counts["taken"] / total, 2) if total else None},
        "last_from_patient": last["in"],
        "last_to_patient": last["out"],
        "created_at": p["created_at"],
    }


def _sort_key(row: dict[str, Any]) -> tuple:
    # Worst status first; inside a status, the one who has waited longest first; then by name so the order is stable.
    return (STATUS_RANK[row["status"]], row["waiting_since"] or "9999", row["name"].lower())


def overview(store: Store) -> dict[str, Any]:
    patients = store.all_patients()
    names = {p["id"]: _display_name(p) for p in patients}
    by_patient: dict[str, list[dict[str, Any]]] = {}
    all_alerts = store.all_alerts()
    for a in all_alerts:
        by_patient.setdefault(a["patient_id"], []).append(a)

    rows = sorted((_patient_row(store, p, by_patient.get(p["id"], [])) for p in patients), key=_sort_key)

    open_alerts = [a for a in all_alerts if not a["acknowledged"] and a["patient_id"] in names]
    open_alerts.sort(key=lambda a: (_level_rank(a), a["created_at"], a["id"]))
    seen = [a for a in all_alerts if a["acknowledged"] and a["patient_id"] in names]
    seen.sort(key=lambda a: (a["acknowledged_at"] or a["created_at"], a["id"]), reverse=True)

    minutes: list[float] = []
    for a in seen:
        t0, t1 = _when(a["created_at"]), _when(a["acknowledged_at"])
        if t0 and t1:
            minutes.append(max(0.0, (t1 - t0).total_seconds() / 60))
    now = datetime.now(timezone.utc)
    seen_today = sum(1 for a in seen if (t := _when(a["acknowledged_at"])) and (now - t).total_seconds() < 86400)

    return {
        "stats": {
            "patients": len(rows),
            **{s: sum(r["status"] == s for r in rows) for s in STATUS_RANK},
            "open_alerts": len(open_alerts),
            "seen_today": seen_today,
            "median_minutes_to_seen": round(median(minutes)) if minutes else None,
        },
        "patients": rows,
        "open_alerts": [_alert_row(a, names) for a in open_alerts],
        "seen_alerts": [_alert_row(a, names) for a in seen[:SEEN_ALERTS_SHOWN]],
        "generated_at": store.clock(),
    }


def patient_detail(engine: CheckInEngine, pid: str) -> dict[str, Any]:
    """The follow-up state of one patient, plus the plan they confirmed, for the care team to read."""
    state = engine.state(pid)
    p = engine.store.get_patient(pid) or {}
    ex = engine.extraction(p)
    names = {pid: _display_name(p)}
    state["alerts"] = [_alert_row(a, names) for a in engine.store.alerts(pid)]
    state["plan"] = {
        "diagnosis": ex.diagnosis_summary,
        "medications": [{"name": m.name, "dose": m.dose, "frequency": m.frequency, "duration": m.duration, "status": m.status}
                        for m in ex.medications],
        "follow_ups": [{"what": f.what, "with_whom": f.with_whom, "when": f.when, "contact": f.contact} for f in ex.follow_ups],
        "restrictions": [r.instruction for r in ex.restrictions],
    }
    state["patient"]["display_name"] = _display_name(p)
    if p["mode"] == "telegram":
        state["telegram"] = {"linked": bool(p["chat_id"])}          # never the one-time connect link: it would let anyone connect as this patient
    return state

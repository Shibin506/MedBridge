"use client";
import { useState } from "react";
import { ago, clockTime } from "@/lib/time";
import type { TeamAlert } from "@/lib/types";

export const LEVEL_LABEL: Record<string, string> = { urgent: "EMERGENCY", same_day: "CALL TODAY", review: "PLEASE READ" };
const NAME_KEY = "medbridge_team_name";

function savedName(): string {
  try { return localStorage.getItem(NAME_KEY) ?? ""; } catch { return ""; }
}

/** One alert for the care team. Open alerts can be marked as seen, with a note about what was done. */
export default function AlertCard({ alert, showPatient, onOpenPatient, onSeen }: {
  alert: TeamAlert; showPatient?: boolean; onOpenPatient?: (id: string) => void;
  onSeen: (id: number, note: string, by: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [by, setBy] = useState(savedName);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true); setError(null);
    try {
      try { localStorage.setItem(NAME_KEY, by.trim()); } catch { /* remembering the name is optional */ }
      await onSeen(alert.id, note, by);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }

  return (
    <div className={`finding ${alert.level === "urgent" ? "danger" : ""} ${alert.acknowledged ? "done" : ""}`}>
      <div className="row">
        <span className={`badge ${alert.level === "urgent" ? "danger" : alert.level === "same_day" ? "changed" : ""}`}>{LEVEL_LABEL[alert.level]}</span>
        {showPatient && (onOpenPatient
          ? <button className="linkish" onClick={() => onOpenPatient(alert.patient_id)}>{alert.patient_name}</button>
          : <strong>{alert.patient_name}</strong>)}
        <strong>{alert.title}</strong>
        <span className="small" title={alert.created_at}>{ago(alert.created_at)}</span>
      </div>
      <p className="small">{alert.detail}</p>
      {alert.acknowledged ? (
        <p className="small">
          ✔ Seen{alert.by ? ` by ${alert.by}` : ""}{alert.acknowledged_at ? ` at ${clockTime(alert.acknowledged_at)} (${ago(alert.acknowledged_at)})` : ""}
          {alert.note ? <> — “{alert.note}”</> : null}
        </p>
      ) : (
        <>
          {alert.next_step && <p className="next-step"><strong>Next step:</strong> {alert.next_step}</p>}
          {!open && <button className="btn" onClick={() => setOpen(true)}>Mark as seen…</button>}
          {open && (
            <form className="form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
              <label>What did you do? (optional, kept with the alert)
                <textarea rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Called at 2:10 PM, advised…" />
              </label>
              <label>Your name (optional)
                <input maxLength={80} value={by} onChange={(e) => setBy(e.target.value)} />
              </label>
              <div className="row">
                <button className="btn primary" type="submit" disabled={busy}>Save as seen</button>
                <button className="btn quiet" type="button" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
              </div>
              {error && <p role="alert" className="error">{error}</p>}
            </form>
          )}
        </>
      )}
    </div>
  );
}

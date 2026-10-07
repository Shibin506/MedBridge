"use client";
import { useEffect, useRef } from "react";
import { ago } from "@/lib/time";
import type { PatientDetailData, TeamStatus } from "@/lib/types";
import AlertCard from "./AlertCard";
import WeightChart from "./WeightChart";

export const STATUS_LABEL: Record<TeamStatus, string> = {
  emergency: "Emergency", call_today: "Call today", review: "Please read", stopped: "Texts stopped", ok: "No open alerts",
};
export const STATUS_BADGE: Record<TeamStatus, string> = { emergency: "danger", call_today: "changed", review: "", stopped: "", ok: "continue" };

/** Everything the care team can see about one patient: alerts, the conversation, weights, and the plan the patient confirmed. */
export default function PatientDetail({ data, status, onBack, onSeen, onOpenSimulator }: {
  data: PatientDetailData; status: TeamStatus; onBack: () => void;
  onSeen: (id: number, note: string, by: string) => Promise<void>; onOpenSimulator: () => void;
}) {
  const thread = useRef<HTMLDivElement>(null);
  useEffect(() => { thread.current?.scrollTo({ top: thread.current.scrollHeight }); }, [data.messages.length]);
  const open = data.alerts.filter((a) => !a.acknowledged);
  const handled = data.alerts.filter((a) => a.acknowledged);
  const { adherence, plan } = data;
  const total = adherence.taken + adherence.missed + adherence.unanswered;

  return (
    <div>
      <button className="btn quiet no-print" onClick={onBack}>← All patients</button>
      <div className="row">
        <h1 style={{ margin: 0 }}>{data.patient.display_name}</h1>
        <span className={`badge ${STATUS_BADGE[status]}`}>{STATUS_LABEL[status]}</span>
      </div>
      <p className="lead">
        {plan.diagnosis ? `${plan.diagnosis.replace(/[.\s]+$/, "")}. ` : ""}Day {data.patient.day} of check-ins ·{" "}
        {data.patient.mode === "simulator" ? "pretend phone (no real texts)" : `texts go to the phone ending in ${data.patient.phone_last4}`}
        {data.patient.opted_out ? " · the patient turned texts off" : ""}
      </p>
      {data.patient.opted_out && (
        <p className="finding">This patient replied STOP, so MedBridge no longer texts them. Nobody is watching them automatically: consider a phone call.</p>
      )}

      <div className="two-col">
        <div>
          <section className="card" aria-label="Alerts">
            <h2>Alerts</h2>
            {open.length === 0 && <p>No open alerts for this patient.</p>}
            {open.map((a) => <AlertCard key={a.id} alert={a} onSeen={onSeen} />)}
            {handled.length > 0 && (
              <details>
                <summary>Handled ({handled.length})</summary>
                {handled.map((a) => <AlertCard key={a.id} alert={a} onSeen={onSeen} />)}
              </details>
            )}
          </section>

          <section className="card" aria-label="Conversation">
            <h2>Conversation</h2>
            <div className="thread" ref={thread}>
              {data.messages.map((m) => (
                <div key={m.id} className={`bubble ${m.direction}`}>
                  <span className="when">{m.direction === "in" ? "Patient" : "MedBridge"} · {m.sim_label} · {ago(m.created_at)}</span>
                  {m.body.split("\n").map((line, i) => <p key={i}>{line}</p>)}
                </div>
              ))}
            </div>
            <p className="small">Read-only. Replies to patients are not sent from this page.</p>
          </section>
        </div>

        <div>
          <section className="card">
            <h2>Weight</h2>
            <WeightChart points={data.weights} />
            {data.weight_rules.length > 0 && <p className="small">Alert if the gain is more than: {data.weight_rules.join(" or ")} (from the patient’s paper).</p>}
          </section>

          <section className="card">
            <h2>Medicines</h2>
            <p>
              Taken: <strong>{adherence.taken}</strong> · Said no: <strong>{adherence.missed}</strong> · No answer: <strong>{adherence.unanswered}</strong>
              {total > 0 && <> · {Math.round((adherence.taken / total) * 100)}% confirmed</>}
            </p>
          </section>

          <section className="card">
            <h2>The plan the patient confirmed</h2>
            <ul className="plain">
              {plan.medications.map((m, i) => (
                <li key={i}>
                  <strong>{m.name}</strong>{m.dose ? ` ${m.dose}` : ""}{m.frequency ? `, ${m.frequency}` : ""}{m.duration ? `, ${m.duration}` : ""}
                  {m.status === "stop" && <span className="badge stop" style={{ marginLeft: 6 }}>STOP</span>}
                </li>
              ))}
            </ul>
            {plan.follow_ups.length > 0 && (
              <>
                <h3>Appointments</h3>
                <ul className="plain">
                  {plan.follow_ups.map((f, i) => <li key={i}>{f.what}{f.with_whom ? ` with ${f.with_whom}` : ""}{f.when ? `, ${f.when}` : ""}{f.contact ? ` · ${f.contact}` : ""}</li>)}
                </ul>
              </>
            )}
            {plan.restrictions.length > 0 && (
              <>
                <h3>Instructions</h3>
                <ul className="plain">{plan.restrictions.map((r, i) => <li key={i}>{r}</li>)}</ul>
              </>
            )}
          </section>

          <details className="card">
            <summary><strong>When this patient raises an alert</strong></summary>
            <p className="small">Rules come from the patient’s own paper. Chest pain, fainting, stroke signs and similar are always emergencies.</p>
            <ul>
              {data.alert_rules.map((r) => <li key={r.sign}><strong>{r.level === "urgent" ? "Call 911" : "Call doctor"}:</strong> {r.sign}</li>)}
            </ul>
          </details>

          {data.patient.mode === "simulator" && (
            <button className="btn" onClick={onOpenSimulator}>Open this patient’s pretend phone</button>
          )}
        </div>
      </div>
    </div>
  );
}

"use client";
import { useEffect, useRef, useState } from "react";
import { ackAlert, advance, getFollowUp, sendReply } from "@/lib/api";
import type { FollowUpState } from "@/lib/types";

const LEVEL_LABEL: Record<string, string> = { urgent: "EMERGENCY", same_day: "CALL TODAY", review: "PLEASE READ" };

function WeightChart({ points }: { points: { day: number; pounds: number }[] }) {
  if (points.length === 0) return <p className="small">No weights yet. They appear after the first check-in.</p>;
  const w = 300, h = 110, pad = 26;
  const xs = points.map((p) => p.day), ys = points.map((p) => p.pounds);
  const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1);
  const y0 = Math.min(...ys) - 2, y1 = Math.max(...ys) + 2;
  const sx = (d: number) => pad + ((d - x0) / (x1 - x0)) * (w - 2 * pad);
  const sy = (v: number) => h - pad - ((v - y0) / (y1 - y0)) * (h - 2 * pad);
  return (
    <>
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Weight by day: ${points.map((p) => `day ${p.day} ${p.pounds} pounds`).join(", ")}`} className="chart">
        <polyline fill="none" stroke="var(--brand)" strokeWidth="2.5" points={points.map((p) => `${sx(p.day)},${sy(p.pounds)}`).join(" ")} />
        {points.map((p) => (
          <g key={p.day}>
            <circle cx={sx(p.day)} cy={sy(p.pounds)} r="4" fill="var(--brand)" />
            <text x={sx(p.day)} y={sy(p.pounds) - 8} textAnchor="middle" fontSize="10" fill="currentColor">{p.pounds}</text>
            <text x={sx(p.day)} y={h - 8} textAnchor="middle" fontSize="10" fill="currentColor">D{p.day}</text>
          </g>
        ))}
      </svg>
    </>
  );
}

export default function FollowUpStep({ initial, onBack }: { initial: FollowUpState; onBack: () => void }) {
  const [state, setState] = useState(initial);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const thread = useRef<HTMLDivElement>(null);
  const pid = state.patient.id;
  const isSim = state.patient.mode === "simulator";

  useEffect(() => { thread.current?.scrollTo({ top: thread.current.scrollHeight }); }, [state.messages.length]);

  async function run(fn: () => Promise<FollowUpState>) {
    setBusy(true); setError(null);
    try { setState(await fn()); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  const lastOut = [...state.messages].reverse().find((m) => m.direction === "out");
  const chips: string[] = [];
  if (lastOut?.kind === "reminder") chips.push("Yes, I took them", "No, I couldn't");
  if (lastOut?.kind === "checkin" || lastOut?.kind === "reply") {
    if (state.checkin_asks_weight) chips.push("172 and no symptoms", "176 and my ankles are swollen");
    else chips.push("None, I feel fine");
  }
  chips.push("I have chest pain", "I feel really bad today", "STOP");

  const open = state.alerts.filter((a) => !a.acknowledged);
  return (
    <div>
      <button className="btn quiet no-print" onClick={onBack}>← Back to my plan</button>
      <h1>Daily check-ins</h1>
      <p className="lead">
        {isSim
          ? "This is a pretend phone. No real texts are sent. Press “Next text” to move through the day, and reply as the patient would."
          : `Real texts are going to the phone ending in ${state.patient.phone_last4}. Replies appear here.`}
      </p>

      <div className="two-col">
        <section className="card phone" aria-label="Text messages">
          <h2>{isSim ? "Patient’s phone" : "Texts"}</h2>
          <div className="thread" ref={thread} aria-live="polite">
            {state.messages.map((m) => (
              <div key={m.id} className={`bubble ${m.direction}`}>
                <span className="when">{m.sim_label}</span>
                {m.body.split("\n").map((line, i) => <p key={i}>{line}</p>)}
              </div>
            ))}
          </div>

          <div className="row">
            {state.next_event && !state.patient.opted_out && (
              <button className="btn primary" disabled={busy} onClick={() => run(() => advance(pid))}>
                Next text: {state.next_event.label}
              </button>
            )}
          </div>
          <div className="row chips" aria-label="Quick replies">
            {chips.map((c) => (
              <button key={c} className="btn chip" disabled={busy} onClick={() => run(() => sendReply(pid, c.replace(/^Yes, I took them$/, "yes").replace(/^No, I couldn't$/, "no")))}>
                {c}
              </button>
            ))}
          </div>
          <form className="row" onSubmit={(e) => { e.preventDefault(); const t = text.trim(); if (t) { setText(""); void run(() => sendReply(pid, t)); } }}>
            <input aria-label="Type a reply" placeholder="Type a reply…" value={text} onChange={(e) => setText(e.target.value)} style={{ flex: 1 }} />
            <button className="btn" disabled={busy || !text.trim()} type="submit">Send</button>
          </form>
          {error && <p role="alert" className="error">{error}</p>}
          <p className="small">Texting is not for emergencies. In an emergency, call 911.</p>
        </section>

        <div>
          <section className="card" aria-label="Care team alerts">
            <h2>Care team view</h2>
            {open.length === 0 && <p>No open alerts. Nothing needs the care team right now.</p>}
            {state.alerts.map((a) => (
              <div key={a.id} className={`finding ${a.level === "urgent" ? "danger" : ""} ${a.acknowledged ? "done" : ""}`}>
                <div className="row">
                  <span className={`badge ${a.level === "urgent" ? "danger" : a.level === "same_day" ? "changed" : ""}`}>{LEVEL_LABEL[a.level]}</span>
                  <strong>{a.title}</strong>
                </div>
                <p className="small">{a.detail}</p>
                {a.acknowledged
                  ? <p className="small">✔ Seen by the care team</p>
                  : <button className="btn" onClick={() => run(async () => { await ackAlert(a.id); return getFollowUp(pid); })}>Mark as seen</button>}
              </div>
            ))}
          </section>

          <section className="card">
            <h2>Weight</h2>
            <WeightChart points={state.weights} />
            {state.weight_rules.length > 0 && <p className="small">Alert if the gain is more than: {state.weight_rules.join(" or ")} (from the patient’s paper).</p>}
          </section>

          <section className="card">
            <h2>Medicines</h2>
            <p>Taken: <strong>{state.adherence.taken}</strong> · Said no: <strong>{state.adherence.missed}</strong> · No answer: <strong>{state.adherence.unanswered}</strong></p>
          </section>

          <details className="card">
            <summary><strong>How the alerts work for this patient</strong></summary>
            <p className="small">
              Every rule below comes from the patient’s own paper, which they checked. Code (not an AI) decides. Anything unclear goes to a person.
              An emergency such as chest pain, fainting or stroke signs always means “call 911”, even if the paper does not list it.
            </p>
            <ul>
              {state.alert_rules.map((r) => (
                <li key={r.sign}><strong>{r.level === "urgent" ? "Call 911" : "Call doctor"}:</strong> {r.sign}</li>
              ))}
            </ul>
          </details>
        </div>
      </div>
    </div>
  );
}

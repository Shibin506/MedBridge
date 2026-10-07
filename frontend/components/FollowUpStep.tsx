"use client";
import { useEffect, useRef, useState } from "react";
import { ackAlert, advance, getFollowUp, sendReply } from "@/lib/api";
import type { FollowUpState } from "@/lib/types";
import WeightChart from "./WeightChart";

const LEVEL_LABEL: Record<string, string> = { urgent: "EMERGENCY", same_day: "CALL TODAY", review: "PLEASE READ" };

export default function FollowUpStep({ initial, onBack, backLabel = "← Back to my plan" }: { initial: FollowUpState; onBack: () => void; backLabel?: string }) {
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
      <button className="btn quiet no-print" onClick={onBack}>{backLabel}</button>
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
              <button className={`btn ${isSim ? "primary" : ""}`} disabled={busy} onClick={() => run(() => advance(pid))}>
                {isSim ? "Next text" : "Send now (for testing)"}: {state.next_event.label}
              </button>
            )}
          </div>
          {!isSim && !state.patient.opted_out && (
            <p className="small">
              {state.scheduled_next
                ? <>Texts go out by themselves at the right time{state.timezone ? ` (${state.timezone})` : ""}. Next one: <strong>{state.scheduled_next.label}</strong>.</>
                : "No more scheduled texts."}
            </p>
          )}
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

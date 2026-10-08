"use client";
import SafetyPanel from "./SafetyPanel";
import SchedulePanel from "./SchedulePanel";
import { useState } from "react";
import type { AppConfig, Extras, PatientPlan, PlanItem } from "@/lib/types";

const STATUS_TEXT: Record<string, string> = { new: "New", changed: "Changed", continue: "Keep taking" };

function ItemList({ items }: { items: PlanItem[] }) {
  return (
    <ul className="plan-list">
      {items.map((i) => (
        <li key={i.id} className={i.emergency ? "emergency" : ""}>
          <p>{i.emergency && <strong>🚨 </strong>}{i.plain_text}</p>
          <details><summary>From your paper</summary><p className="small">{i.original}</p></details>
        </li>
      ))}
    </ul>
  );
}

interface Props {
  plan: PatientPlan; extras: Extras | null; config: AppConfig; busy: boolean; error: string | null;
  onBack: () => void; onLanguage: (code: string) => void;
  onStartCheckins: (c: { mode: "simulator" | "sms" | "telegram"; phone?: string; consent: boolean; name?: string }) => void; checkinError: string | null;
}

export default function PlanStep({ plan, extras, config, busy, error, onBack, onLanguage, onStartCheckins, checkinError }: Props) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [consent, setConsent] = useState(false);
  const stopped = plan.medications.filter((m) => m.status === "stop");
  const taking = plan.medications.filter((m) => m.status !== "stop");
  const rtl = plan.language === "ar";

  return (
    <div dir={rtl ? "rtl" : "ltr"} lang={plan.language}>
      <div className="row no-print" dir="ltr">
        <button className="btn quiet" onClick={onBack}>← Back to checking</button>
        <label className="inline">Language
          <select value={plan.language} disabled={busy} onChange={(e) => onLanguage(e.target.value)}>
            {Object.entries(config.languages).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
        </label>
        <button className="btn" onClick={() => window.print()}>Print or save as PDF</button>
      </div>
      {busy && <p role="status" className="note">Writing your plan in {plan.language_name}…</p>}
      {error && <p role="alert" className="error">{error}</p>}

      <h1>Your plan</h1>
      <p className="lead">{plan.summary}</p>

      <SafetyPanel report={extras?.safety ?? null} />

      {stopped.length > 0 && (
        <section className="card danger-card">
          <h2>Stop taking</h2>
          {stopped.map((m) => (
            <div key={m.id} className="med"><h3>{m.name}</h3><p>{m.how_to_take}</p>
              {m.why_taking && <p className="small">{m.why_taking}</p>}</div>
          ))}
        </section>
      )}

      <SchedulePanel schedule={extras?.schedule ?? null} />

      {taking.length > 0 && (
        <section className="card">
          <h2>Your medicines</h2>
          {taking.map((m) => (
            <div key={m.id} className="med">
              <h3>{m.name} {m.dose && <span className="dose">{m.dose}</span>}
                <span className={`badge ${m.status}`}>{STATUS_TEXT[m.status]}</span></h3>
              <p>{m.how_to_take}</p>
              {m.missing_info.length > 0 && (
                <p className="missing" dir="ltr" lang="en">
                  ⚠ Your paper does not say {m.missing_info.map((k) => (k === "dose" ? "how much" : "how often")).join(" or ")} to take this.
                  Please ask your care team.
                </p>
              )}
              {m.why_taking && (
                <p className="small">
                  <em>{m.why_source === "your_paper" ? "From your paper: " : "General information, not from your paper: "}</em>
                  {m.why_taking}
                </p>
              )}
            </div>
          ))}
        </section>
      )}

      {plan.follow_ups.length > 0 && <section className="card"><h2>Appointments and tests</h2><ItemList items={plan.follow_ups} /></section>}
      {plan.warning_signs.length > 0 && <section className="card"><h2>Warning signs</h2><ItemList items={plan.warning_signs} /></section>}
      {plan.restrictions.length > 0 && <section className="card"><h2>Daily care at home</h2><ItemList items={plan.restrictions} /></section>}

      <section className="card no-print" dir="ltr" lang="en">
        <h2>Reminders and daily check-ins</h2>
        <p>MedBridge can text you when it is time for each medicine, and check in each morning. If you report a warning sign from your
          paper, it tells you what your paper says to do and alerts your care team. <strong>Texting is not for emergencies: call 911.</strong></p>
        <div className="form">
          <label>Patient’s name (optional, so the care team can tell patients apart)
            <input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </label>
        </div>
        <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => onStartCheckins({ mode: "simulator", consent: false, name: name.trim() || undefined })}>
            Try it on the phone simulator
          </button>
        </div>
        {config.telegram && (
          <div className="form">
            <h3>Get the messages on Telegram (free)</h3>
            <p className="small">Real messages on your phone with no phone-company approval. You open a link and press Start in Telegram; pressing Start means you agree to receive messages. Reply STOP any time.</p>
            <button className="btn primary" disabled={busy} onClick={() => onStartCheckins({ mode: "telegram", consent: true, name: name.trim() || undefined })}>
              Connect Telegram
            </button>
          </div>
        )}
        {config.sms && (
          <div className="form">
            <label>Your mobile number (for example +15551234567)
              <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" autoComplete="tel" />
            </label>
            <label className="check">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              I agree to receive text messages from MedBridge. Message and data rates may apply. I can reply STOP at any time.
            </label>
            <button className="btn" disabled={busy || !consent || !phone.trim()} onClick={() => onStartCheckins({ mode: "sms", phone, consent, name: name.trim() || undefined })}>
              Text my phone
            </button>
          </div>
        )}
        {checkinError && <p role="alert" className="error">{checkinError}</p>}
      </section>

      <section className="card disclaimer">
        <p>{plan.disclaimer}</p>
        {plan.language !== "en" && <p className="small" dir="ltr" lang="en">{plan.disclaimer_en}</p>}
      </section>
    </div>
  );
}

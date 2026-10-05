"use client";
import type { AppConfig, PatientPlan, PlanItem } from "@/lib/types";

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
  plan: PatientPlan; config: AppConfig; busy: boolean; error: string | null;
  onBack: () => void; onLanguage: (code: string) => void;
}

export default function PlanStep({ plan, config, busy, error, onBack, onLanguage }: Props) {
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

      {stopped.length > 0 && (
        <section className="card danger-card">
          <h2>Stop taking</h2>
          {stopped.map((m) => (
            <div key={m.id} className="med"><h3>{m.name}</h3><p>{m.how_to_take}</p>
              {m.why_taking && <p className="small">{m.why_taking}</p>}</div>
          ))}
        </section>
      )}

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

      <section className="card disclaimer">
        <p>{plan.disclaimer}</p>
        {plan.language !== "en" && <p className="small" dir="ltr" lang="en">{plan.disclaimer_en}</p>}
      </section>
    </div>
  );
}

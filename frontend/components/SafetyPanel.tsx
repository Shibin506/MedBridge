import type { SafetyReport } from "@/lib/types";

/** Everything here comes from plain code and public drug information, never from the AI that wrote the plan. */
export default function SafetyPanel({ report }: { report: SafetyReport | null }) {
  if (!report) {
    return (
      <section className="card notice" dir="ltr" lang="en">
        <h2>Safety check</h2>
        <p>We could not run the medicine safety check this time. Please ask your pharmacist to review your full list.</p>
      </section>
    );
  }
  const findings = report.duplicates.length + report.stopped_conflicts.length + report.interactions.length + report.daily_totals.length;
  return (
    <section className={`card ${findings ? "notice" : ""}`} dir="ltr" lang="en">
      <h2>Safety check{findings ? ": please read" : ""}</h2>

      {report.daily_totals.map((t) => (
        <div key={t.ingredient} className="finding danger">
          <strong>Too much {t.ingredient} in one day: about {t.total_mg.toLocaleString()} mg (limit {t.limit_mg.toLocaleString()} mg)</strong>
          <p>{t.message}</p>
        </div>
      ))}
      {report.duplicates.map((d) => (
        <div key={d.ingredient} className="finding danger"><strong>Same ingredient twice: {d.ingredient}</strong>
          <p>{d.message}</p></div>
      ))}
      {report.stopped_conflicts.map((c) => (
        <div key={`${c.stopped}-${c.still_listed}`} className="finding danger"><strong>Conflicting instructions: {c.ingredient}</strong>
          <p>{c.message}</p></div>
      ))}
      {report.interactions.map((h) => (
        <div key={`${h.drug_a}-${h.drug_b}`} className="finding">
          <strong>{h.drug_a} and {h.drug_b}: ask your pharmacist</strong>
          <p>“{h.excerpt}”</p>
          <p className="small">Source: {h.source}</p>
        </div>
      ))}

      {findings === 0 && report.interaction_check === "done" && (
        <p>No duplicate medicines or conflicting instructions were found, and we found no warnings in the drug information we checked.</p>
      )}
      {findings === 0 && report.interaction_check === "not_run" && <p>No duplicate medicines or conflicting instructions were found.</p>}
      {report.interaction_check === "unavailable" && (
        <p className="finding"><strong>Interactions were NOT checked</strong> because the drug-information service could not be reached.</p>
      )}
      {report.notes.map((n) => <p key={n} className="small">{n}</p>)}
    </section>
  );
}

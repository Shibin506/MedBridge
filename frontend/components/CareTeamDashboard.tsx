"use client";
import { useCallback, useEffect, useState } from "react";
import { AuthError, ackAlert, getDashboard, getFollowUp, getPatientDetail, getTeamKey, loadExamples, removeExamples, setTeamKey } from "@/lib/api";
import { ago, clockTime } from "@/lib/time";
import type { AppConfig, DashboardData, FollowUpState, PatientDetailData, TeamPatient, TeamStatus } from "@/lib/types";
import AlertCard from "./AlertCard";
import PatientDetail, { STATUS_BADGE, STATUS_LABEL } from "./PatientDetail";

const REFRESH_MS = 10_000;
const FILTERS: { key: TeamStatus | "all"; label: string }[] = [
  { key: "all", label: "Everyone" }, { key: "emergency", label: STATUS_LABEL.emergency }, { key: "call_today", label: STATUS_LABEL.call_today },
  { key: "review", label: STATUS_LABEL.review }, { key: "stopped", label: STATUS_LABEL.stopped }, { key: "ok", label: STATUS_LABEL.ok },
];

/** First sentence, at most ~90 characters: enough to recognise the patient in a list. */
function brief(text: string): string {
  const first = text.split(/(?<=[.!?])\s/)[0];
  return first.length > 90 ? first.slice(0, 87).replace(/\s+\S*$/, "") + "…" : first;
}

function Spark({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const w = 56, h = 18, lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - lo) / span) * (h - 4)}`).join(" ");
  return <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.8" /></svg>;
}

function AccessForm({ onSave, wrong }: { onSave: (key: string) => void; wrong: boolean }) {
  const [key, setKey] = useState("");
  return (
    <form className="card form" onSubmit={(e) => { e.preventDefault(); onSave(key.trim()); }}>
      <h2>Care-team access code</h2>
      <p className="small">This page shows every patient, so the server asks for a code (set as MEDBRIDGE_TEAM_KEY on the server).</p>
      <label>Access code
        <input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
      </label>
      {wrong && <p role="alert" className="error">That code was not accepted.</p>}
      <button className="btn primary" type="submit" disabled={!key.trim()}>Open dashboard</button>
    </form>
  );
}

export default function CareTeamDashboard({ config, onOpenSimulator }: { config: AppConfig; onOpenSimulator: (state: FollowUpState) => void }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [detail, setDetail] = useState<PatientDetailData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<TeamStatus | "all">("all");
  const [needKey, setNeedKey] = useState(config.team_key_required && !getTeamKey());
  const [keyWrong, setKeyWrong] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setData(await getDashboard());
      if (selected) setDetail(await getPatientDetail(selected));
      setError(null); setNeedKey(false);
    } catch (e) {
      if (e instanceof AuthError) { setNeedKey(true); setKeyWrong(!!getTeamKey()); setTeamKey(""); }
      else setError((e as Error).message);
    }
  }, [selected]);

  useEffect(() => {
    if (needKey) return;
    void refresh();
    const timer = setInterval(() => { if (!document.hidden) void refresh(); }, REFRESH_MS);   // texts arrive while the page is open
    return () => clearInterval(timer);
  }, [refresh, needKey]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try { await fn(); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const seen = async (id: number, note: string, by: string) => { await ackAlert(id, note, by); await refresh(); };

  async function open(pid: string) {
    setSelected(pid); setDetail(null);
    try { setDetail(await getPatientDetail(pid)); } catch (e) { setError((e as Error).message); }
  }

  if (needKey) return <AccessForm wrong={keyWrong} onSave={(k) => { setTeamKey(k); setKeyWrong(false); setNeedKey(false); }} />;

  if (selected) {
    const row = data?.patients.find((p) => p.id === selected);
    return detail ? (
      <PatientDetail data={detail} status={row?.status ?? "ok"} onBack={() => { setSelected(null); setDetail(null); }} onSeen={seen}
        onOpenSimulator={() => void getFollowUp(selected).then(onOpenSimulator)} />
    ) : (
      <div><button className="btn quiet" onClick={() => setSelected(null)}>← All patients</button>{error ? <p role="alert" className="error">{error}</p> : <p>Loading…</p>}</div>
    );
  }

  const stats = data?.stats;
  const rows: TeamPatient[] = (data?.patients ?? []).filter((p) => filter === "all" || p.status === filter);

  return (
    <div>
      <div className="row between">
        <h1 style={{ margin: 0 }}>Care team</h1>
        <span className="small" aria-live="polite">{data ? `Updated ${clockTime(data.generated_at)} · refreshes by itself` : ""}</span>
      </div>
      <p className="lead">Everyone who is getting check-in texts, with the people who need a call first. Code (not an AI) decides who is at the top.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {!config.team_key_required && (
        <p className="small notice-line">No access code is set (MEDBRIDGE_TEAM_KEY), so anyone who can reach this server can see this page. Fine on your own computer, not on the internet.</p>
      )}

      {data && data.patients.length === 0 && (
        <section className="card">
          <h2>No patients yet</h2>
          <p>Patients appear here once they start daily check-ins (on the “Patient” side, after confirming a discharge paper). To see how this page looks with a full caseload, load made-up example patients.</p>
          <button className="btn primary" disabled={busy} onClick={() => void act(loadExamples)}>Load 6 example patients</button>
        </section>
      )}

      {stats && data && data.patients.length > 0 && (
        <>
          <div className="tiles" role="group" aria-label="Filter patients by status">
            {FILTERS.map((f) => {
              const count = f.key === "all" ? stats.patients : stats[f.key];
              return (
                <button key={f.key} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}
                  className={`tile ${f.key} ${filter === f.key ? "on" : ""} ${count === 0 ? "zero" : ""}`}>
                  <span className="n">{count}</span><span>{f.label}</span>
                </button>
              );
            })}
          </div>
          <p className="small">
            {stats.open_alerts} open alert{stats.open_alerts === 1 ? "" : "s"} · {stats.seen_today} handled in the last 24 h
            {stats.median_minutes_to_seen !== null && <> · typical time from alert to “seen”: {stats.median_minutes_to_seen} min</>}
          </p>

          <section className="card" aria-label="Open alerts">
            <h2>Needs a person ({data.open_alerts.length})</h2>
            {data.open_alerts.length === 0 && <p>Nothing is waiting. New alerts show up here by themselves.</p>}
            {data.open_alerts.map((a) => <AlertCard key={a.id} alert={a} showPatient onOpenPatient={open} onSeen={seen} />)}
          </section>

          <section className="card" aria-label="Patients">
            <h2>Patients ({rows.length}{filter !== "all" ? ` of ${stats.patients}` : ""})</h2>
            {rows.length === 0 && <p>No patients with this status.</p>}
            {rows.length > 0 && (
              <table className="team">
                <thead>
                  <tr><th scope="col">Status</th><th scope="col">Patient</th><th scope="col">Latest</th><th scope="col">Weight</th><th scope="col">Medicines</th><th scope="col">Last heard</th></tr>
                </thead>
                <tbody>
                  {rows.map((p) => (
                    <tr key={p.id} className={p.status}>
                      <td data-label="Status"><span className={`badge ${STATUS_BADGE[p.status]}`}>{p.status_label}</span></td>
                      <td data-label="Patient">
                        <button className="linkish" onClick={() => void open(p.id)}>{p.name}</button>
                        <div className="small">Day {p.day}{p.diagnosis ? ` · ${brief(p.diagnosis)}` : ""}</div>
                      </td>
                      <td data-label="Latest">{p.top_alert ?? (!p.connected ? "Has not connected Telegram yet" : p.opted_out ? "Replied STOP" : "—")}
                        {p.waiting_since && <div className="small">waiting {ago(p.waiting_since).replace(" ago", "")}</div>}</td>
                      <td data-label="Weight">{p.weight ? <>{p.weight.latest} lb <span className="small">({p.weight.change > 0 ? "+" : ""}{p.weight.change})</span> <Spark values={p.weight.trend} /></> : "—"}</td>
                      <td data-label="Medicines">{p.adherence.rate === null ? "—" : `${Math.round(p.adherence.rate * 100)}% confirmed`}
                        {p.adherence.unanswered > 0 && <div className="small">{p.adherence.unanswered} no answer</div>}</td>
                      <td data-label="Last heard">{p.last_from_patient ? ago(p.last_from_patient.created_at) : "never"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {data.seen_alerts.length > 0 && (
            <details className="card">
              <summary><strong>Recently handled ({data.seen_alerts.length})</strong></summary>
              {data.seen_alerts.map((a) => <AlertCard key={a.id} alert={a} showPatient onOpenPatient={open} onSeen={seen} />)}
            </details>
          )}

          <p className="small">
            Example patients are made up.{" "}
            <button className="linkish" disabled={busy} onClick={() => void act(loadExamples)}>Reload the examples</button>{" · "}
            <button className="linkish" disabled={busy} onClick={() => void act(removeExamples)}>Remove the examples</button>
          </p>
        </>
      )}
    </div>
  );
}

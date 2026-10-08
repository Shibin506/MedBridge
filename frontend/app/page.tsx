"use client";
import { useEffect, useState } from "react";
import ConfirmStep from "@/components/ConfirmStep";
import PlanStep from "@/components/PlanStep";
import UploadStep from "@/components/UploadStep";
import FollowUpStep from "@/components/FollowUpStep";
import CareTeamDashboard from "@/components/CareTeamDashboard";
import { createPatient, getConfig, getSafety, getSchedule, makePlan } from "@/lib/api";
import type { AppConfig, Extras, ExtractionResult, FollowUpState, PatientPlan } from "@/lib/types";

type Opts = { language: string; reading_level: string; acknowledged_unclear: boolean; acknowledged_review: boolean };

export default function Home() {
  const [config, setConfig] = useState<AppConfig>({ demo: false, languages: { en: "English" }, sms: false, telegram: false, team_key_required: false });
  const [view, setView] = useState<"patient" | "team">("patient");
  const [teamSim, setTeamSim] = useState<FollowUpState | null>(null);   // a pretend phone opened from the care-team page
  const [followUp, setFollowUp] = useState<FollowUpState | null>(null);
  const [followUpError, setFollowUpError] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<ExtractionResult | null>(null);
  const [plan, setPlan] = useState<PatientPlan | null>(null);
  const [extras, setExtras] = useState<Extras | null>(null);
  const [opts, setOpts] = useState<Opts | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { getConfig().then(setConfig).catch(() => undefined); }, []);
  useEffect(() => { if (window.location.hash === "#team") setView("team"); }, []);
  function show(next: "patient" | "team") {
    setView(next); setTeamSim(null);
    window.history.replaceState(null, "", next === "team" ? "#team" : window.location.pathname);
  }

  async function generate(next: Opts) {
    if (!extraction) return;
    setBusy(true); setError(null); setOpts(next);
    const body = { extraction, ...next };
    try {
      // The schedule and safety check do not depend on the language, so they are fetched once per
      // confirmed list and kept when the patient only switches language. If either fails, the plan
      // still shows and the screen says that part could not be loaded.
      const [p, sched, safety] = await Promise.all([
        makePlan(body),
        extras ? Promise.resolve(extras.schedule) : getSchedule(body).catch(() => null),
        extras ? Promise.resolve(extras.safety) : getSafety(body).catch(() => null),
      ]);
      setPlan(p); setExtras({ schedule: sched, safety });
    }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function startCheckins(choice: { mode: "simulator" | "sms" | "telegram"; phone?: string; consent: boolean; name?: string }) {
    if (!extraction || !opts) return;
    setBusy(true); setFollowUpError(null);
    try {
      setFollowUp(await createPatient({
        plan: { extraction, ...opts }, mode: choice.mode, phone: choice.phone, consent_sms: choice.consent, name: choice.name,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }));
    } catch (e) { setFollowUpError((e as Error).message); } finally { setBusy(false); }
  }

  function reset() { setExtraction(null); setPlan(null); setExtras(null); setOpts(null); setError(null); setFollowUp(null); }

  return (
    <>
      <header className="topbar no-print">
        <span className="brand">MedBridge</span>
        <span className="tag">Plain-language help after the hospital</span>
        <nav className="nav" aria-label="Who is using MedBridge">
          <button className={`navbtn ${view === "patient" ? "on" : ""}`} aria-current={view === "patient" ? "page" : undefined} onClick={() => show("patient")}>Patient</button>
          <button className={`navbtn ${view === "team" ? "on" : ""}`} aria-current={view === "team" ? "page" : undefined} onClick={() => show("team")}>Care team</button>
        </nav>
      </header>
      {config.demo && (
        <p className="demo-banner no-print">
          Demo mode: answers are pre-written and no AI is running. One medicine in the heart-failure example is
          deliberately made up, to show how the checker catches it.
        </p>
      )}
      <main>
        {view === "team" && !teamSim && <CareTeamDashboard config={config} onOpenSimulator={setTeamSim} />}
        {view === "team" && teamSim && <FollowUpStep initial={teamSim} backLabel="← Back to the care-team page" onBack={() => setTeamSim(null)} />}
        {view === "patient" && (
          <>
            {!extraction && <UploadStep onDone={setExtraction} />}
            {extraction && !plan && !followUp && (
              <ConfirmStep extraction={extraction} config={config} busy={busy} error={error}
                onChange={setExtraction} onBack={reset} onMakePlan={generate} />
            )}
            {followUp && <FollowUpStep initial={followUp} onBack={() => setFollowUp(null)} />}
            {extraction && plan && !followUp && (
              <PlanStep plan={plan} extras={extras} config={config} busy={busy} error={error}
                onBack={() => { setPlan(null); setExtras(null); setError(null); }}
                onStartCheckins={startCheckins} checkinError={followUpError}
                onLanguage={(language) => opts && void generate({ ...opts, language })} />
            )}
          </>
        )}
      </main>
    </>
  );
}

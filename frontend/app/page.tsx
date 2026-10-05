"use client";
import { useEffect, useState } from "react";
import ConfirmStep from "@/components/ConfirmStep";
import PlanStep from "@/components/PlanStep";
import UploadStep from "@/components/UploadStep";
import { getConfig, makePlan } from "@/lib/api";
import type { AppConfig, ExtractionResult, PatientPlan } from "@/lib/types";

type Opts = { language: string; reading_level: string; acknowledged_unclear: boolean };

export default function Home() {
  const [config, setConfig] = useState<AppConfig>({ demo: false, languages: { en: "English" } });
  const [extraction, setExtraction] = useState<ExtractionResult | null>(null);
  const [plan, setPlan] = useState<PatientPlan | null>(null);
  const [opts, setOpts] = useState<Opts | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { getConfig().then(setConfig).catch(() => undefined); }, []);

  async function generate(next: Opts) {
    if (!extraction) return;
    setBusy(true); setError(null); setOpts(next);
    try { setPlan(await makePlan({ extraction, ...next })); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function reset() { setExtraction(null); setPlan(null); setOpts(null); setError(null); }

  return (
    <>
      <header className="topbar no-print">
        <span className="brand">MedBridge</span>
        <span className="tag">Plain-language help after the hospital</span>
      </header>
      {config.demo && (
        <p className="demo-banner no-print">
          Demo mode: answers are pre-written and no AI is running. One medicine in the heart-failure example is
          deliberately made up, to show how the checker catches it.
        </p>
      )}
      <main>
        {!extraction && <UploadStep onDone={setExtraction} />}
        {extraction && !plan && (
          <ConfirmStep extraction={extraction} config={config} busy={busy} error={error}
            onChange={setExtraction} onBack={reset} onMakePlan={generate} />
        )}
        {extraction && plan && (
          <PlanStep plan={plan} config={config} busy={busy} error={error}
            onBack={() => { setPlan(null); setError(null); }}
            onLanguage={(language) => opts && void generate({ ...opts, language })} />
        )}
      </main>
    </>
  );
}

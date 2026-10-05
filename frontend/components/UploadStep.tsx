"use client";
import { useEffect, useRef, useState } from "react";
import { extract, getSample, listSamples } from "@/lib/api";
import type { ExtractionResult } from "@/lib/types";

const LABELS: Record<string, string> = {
  "01_heart_failure.txt": "Heart failure (fictional patient)",
  "02_pneumonia.txt": "Pneumonia (fictional patient)",
  "03_hip_replacement.txt": "Hip replacement (fictional patient)",
  "04_gallbladder_surgery.txt": "Gallbladder surgery: duplicates and conflicts (fictional patient)",
};

export default function UploadStep({ onDone }: { onDone: (ex: ExtractionResult) => void }) {
  const [samples, setSamples] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { listSamples().then(setSamples).catch(() => setSamples([])); }, []);

  async function run(file: File) {
    setBusy(true); setError(null);
    try { onDone(await extract(file)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function runSample(name: string) {
    const { text } = await getSample(name);
    await run(new File([text], name, { type: "text/plain" }));
  }

  return (
    <section className="card">
      <h1>Understand your discharge papers</h1>
      <p className="lead">
        Upload the instructions the hospital gave you. We will show you what we understood, you check it,
        and then we make a plan in plain language.
      </p>

      <div
        className="drop"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) void run(f); }}
      >
        <p><strong>Drop a PDF or text file here</strong></p>
        <button className="btn primary" disabled={busy} onClick={() => input.current?.click()}>Choose a file</button>
        <input ref={input} type="file" accept=".pdf,.txt" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void run(f); }} />
      </div>

      {samples.length > 0 && (
        <>
          <h2>No papers handy? Try a fictional example</h2>
          <div className="row">
            {samples.map((s) => (
              <button key={s} className="btn" disabled={busy} onClick={() => void runSample(s)}>
                {LABELS[s] ?? s}
              </button>
            ))}
          </div>
        </>
      )}

      {busy && <p role="status" className="note">Reading your paper… this can take up to a minute.</p>}
      {error && <p role="alert" className="error">{error}</p>}
      <p className="small">Scanned photos are not supported yet; use a PDF or text file. Do not upload papers you are not allowed to share.</p>
    </section>
  );
}

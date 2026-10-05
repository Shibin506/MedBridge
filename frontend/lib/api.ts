import type { AppConfig, DailySchedule, ExtractionResult, PatientPlan, SafetyReport } from "./types";

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let message = `Something went wrong (${res.status}).`;
  try {
    const body = await res.json();
    const d = body.detail;
    if (typeof d === "string") message = d;
    else if (d?.problems) message = (d.problems as string[]).join(" ");
  } catch { /* keep the generic message */ }
  throw new Error(message);
}

export const getConfig = () => fetch("/api/config").then((r) => parse<AppConfig>(r));
export const listSamples = () => fetch("/api/samples").then((r) => parse<string[]>(r));
export const getSample = (name: string) =>
  fetch(`/api/samples/${encodeURIComponent(name)}`).then((r) => parse<{ name: string; text: string }>(r));

export function extract(file: File): Promise<ExtractionResult> {
  const form = new FormData();
  form.append("file", file);
  return fetch("/api/extract", { method: "POST", body: form }).then((r) => parse<ExtractionResult>(r));
}

export interface PlanBody {
  extraction: ExtractionResult; language: string; reading_level: string; acknowledged_unclear: boolean;
  acknowledged_review: boolean;
}

const post = <T,>(path: string, body: PlanBody) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => parse<T>(r));

export const makePlan = (body: PlanBody) => post<PatientPlan>("/api/plan", body);
export const getSchedule = (body: PlanBody) => post<DailySchedule>("/api/schedule", body);
export const getSafety = (body: PlanBody) => post<SafetyReport>("/api/safety", body);

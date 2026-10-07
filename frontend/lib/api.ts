import type { AppConfig, DailySchedule, DashboardData, ExtractionResult, FollowUpState, PatientDetailData, PatientPlan, SafetyReport } from "./types";

/** The care-team pages answered "access code needed". */
export class AuthError extends Error {}

const TEAM_KEY = "medbridge_team_key";
export function getTeamKey(): string {
  try { return sessionStorage.getItem(TEAM_KEY) ?? ""; } catch { return ""; }
}
export function setTeamKey(key: string): void {
  try { key ? sessionStorage.setItem(TEAM_KEY, key) : sessionStorage.removeItem(TEAM_KEY); } catch { /* private window: the code is simply asked for again */ }
}
function teamHeaders(json = false): Record<string, string> {
  const key = getTeamKey();
  return { ...(json ? { "Content-Type": "application/json" } : {}), ...(key ? { "X-Team-Key": key } : {}) };
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  if (res.status === 401) throw new AuthError("The care-team access code is missing or wrong.");
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

export const createPatient = (body: {
  plan: PlanBody; mode: "simulator" | "sms"; phone?: string; consent_sms?: boolean; name?: string;
}) => fetch("/api/patients", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
  .then((r) => parse<FollowUpState>(r));
export const getFollowUp = (id: string) => fetch(`/api/patients/${id}`).then((r) => parse<FollowUpState>(r));
export const advance = (id: string) => fetch(`/api/patients/${id}/advance`, { method: "POST" }).then((r) => parse<FollowUpState>(r));
export const sendReply = (id: string, text: string) =>
  fetch(`/api/patients/${id}/reply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })
    .then((r) => parse<FollowUpState>(r));
export const ackAlert = (alertId: number, note = "", by = "") =>
  fetch(`/api/alerts/${alertId}/ack`, { method: "POST", headers: teamHeaders(true), body: JSON.stringify({ note, by }) })
    .then((r) => parse<{ ok: boolean }>(r));

// ---- care team (phase 5)
export const getDashboard = () => fetch("/api/dashboard", { headers: teamHeaders() }).then((r) => parse<DashboardData>(r));
export const getPatientDetail = (id: string) =>
  fetch(`/api/dashboard/patients/${encodeURIComponent(id)}`, { headers: teamHeaders() }).then((r) => parse<PatientDetailData>(r));
export const loadExamples = () => fetch("/api/demo/patients", { method: "POST", headers: teamHeaders() }).then((r) => parse<{ loaded: number }>(r));
export const removeExamples = () => fetch("/api/demo/patients", { method: "DELETE", headers: teamHeaders() }).then((r) => parse<{ removed: number }>(r));

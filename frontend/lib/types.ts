// Mirrors backend/app/schemas.py. If you change one, change the other.
export type Status = "new" | "changed" | "continue" | "stop";
export type Route =
  | "oral" | "sublingual" | "inhaled" | "topical" | "ophthalmic" | "otic" | "nasal"
  | "rectal" | "subcutaneous" | "intramuscular" | "intravenous" | "other";
export type Category = "medications" | "follow_ups" | "warning_signs" | "restrictions";

interface Verified {
  source_quote: string;
  grounded: boolean;
  needs_confirmation: boolean;
  issues: string[];
  patient_confirmed: boolean;
}
export interface Medication extends Verified {
  name: string; dose: string | null; route: Route | null; frequency: string | null;
  duration: string | null; purpose: string | null; instructions: string | null; status: Status;
  previous_dose: string | null;
}
export interface FollowUp extends Verified { what: string; with_whom: string | null; when: string | null; contact: string | null }
export interface WarningSign extends Verified { symptom: string; action: string }
export type RestrictionCategory = "diet" | "activity" | "wound_care" | "monitoring" | "medication_limit" | "other";
export interface Restriction extends Verified { category: RestrictionCategory; instruction: string }
export type AnyItem = Medication | FollowUp | WarningSign | Restriction;

export interface ExtractionResult {
  diagnosis_summary: string | null;
  medications: Medication[];
  follow_ups: FollowUp[];
  warning_signs: WarningSign[];
  restrictions: Restriction[];
  unclear_items: string[];
  total_items: number;
  items_needing_confirmation: number;
  document_text: string;
  uncovered_lines: string[];
}

export interface PlanMedication {
  id: string; status: Status; name: string; dose: string | null; frequency: string | null;
  how_to_take: string; why_taking: string | null; why_source: "your_paper" | "general_knowledge" | null;
  missing_info: ("dose" | "frequency")[];
}
export interface PlanItem { id: string; plain_text: string; original: string; emergency: boolean }
export interface PatientPlan {
  language: string; language_name: string; reading_level: string; summary: string;
  medications: PlanMedication[]; follow_ups: PlanItem[]; warning_signs: PlanItem[]; restrictions: PlanItem[];
  disclaimer: string; disclaimer_en: string;
}
export interface AppConfig { demo: boolean; languages: Record<string, string>; sms: boolean; team_key_required: boolean }

export interface FollowUpState {
  patient: { id: string; name: string | null; mode: "simulator" | "sms"; opted_out: boolean; phone_last4: string; day: number };
  messages: { id: number; direction: "in" | "out"; body: string; kind: string; sim_label: string; delivery?: string }[];
  alerts: { id: number; level: "urgent" | "same_day" | "review"; title: string; detail: string; day: number; acknowledged: boolean }[];
  weights: { day: number; pounds: number }[];
  adherence: { taken: number; missed: number; unanswered: number };
  next_event: { label: string; kind: string } | null;
  alert_rules: { sign: string; action: string; level: string }[];
  weight_rules: string[];
  checkin_asks_weight: boolean;
  scheduled_next?: { at: string; label: string } | null;   // real texts only: when the next text goes out by itself
  timezone?: string;
}

export interface ScheduleItem { name: string; dose: string | null; note: string | null; status: Status }
export interface ScheduleSlot { time: string; label: string; items: ScheduleItem[] }
export interface DailySchedule {
  slots: ScheduleSlot[];
  as_needed: { name: string; dose: string | null; how_often: string | null; note: string | null }[];
  tapers: { name: string; steps: { when: string; dose: string }[]; after: string | null; note: string | null }[];
  unscheduled: { name: string; reason: string }[];
}
export interface SafetyReport {
  normalized: { name: string; ingredients: string[]; source: "local" | "rxnorm" | "name" }[];
  duplicates: { ingredient: string; medicines: string[]; message: string }[];
  stopped_conflicts: { ingredient: string; stopped: string; still_listed: string; message: string }[];
  interactions: { drug_a: string; drug_b: string; source: string; excerpt: string }[];
  interaction_check: "done" | "partial" | "unavailable" | "not_run";
  notes: string[];
  daily_totals: { ingredient: string; total_mg: number; limit_mg: number; limit_source: string; message: string;
    contributors: { name: string; mg_per_day: number }[] }[];
}
export interface Extras { schedule: DailySchedule | null; safety: SafetyReport | null }

// ---- care-team dashboard
export type AlertLevel = "urgent" | "same_day" | "review";
export type TeamStatus = "emergency" | "call_today" | "review" | "stopped" | "ok";
export interface TeamAlert {
  id: number; patient_id: string; patient_name: string; level: AlertLevel; title: string; detail: string; day: number;
  created_at: string; acknowledged: boolean; acknowledged_at: string | null; note: string; by: string; next_step: string;
}
export interface TeamMessage { direction: "in" | "out"; body: string; kind: string; sim_label: string; created_at: string }
export interface TeamPatient {
  id: string; name: string; mode: "simulator" | "sms"; day: number; diagnosis: string | null; medicine_count: number;
  status: TeamStatus; status_label: string; opted_out: boolean; open_alerts: number; open_by_level: Record<AlertLevel, number>;
  top_alert: string | null; waiting_since: string | null;
  weight: { latest: number; change: number; trend: number[] } | null;
  adherence: { taken: number; missed: number; unanswered: number; rate: number | null };
  last_from_patient: TeamMessage | null; last_to_patient: TeamMessage | null; created_at: string;
}
export interface DashboardData {
  stats: { patients: number; emergency: number; call_today: number; review: number; stopped: number; ok: number;
    open_alerts: number; seen_today: number; median_minutes_to_seen: number | null };
  patients: TeamPatient[]; open_alerts: TeamAlert[]; seen_alerts: TeamAlert[]; generated_at: string;
}
export interface PatientDetailData extends Omit<FollowUpState, "alerts" | "patient" | "messages"> {
  patient: FollowUpState["patient"] & { display_name: string };
  messages: (FollowUpState["messages"][number] & { created_at: string })[];
  alerts: TeamAlert[];
  plan: {
    diagnosis: string | null;
    medications: { name: string; dose: string | null; frequency: string | null; duration: string | null; status: string }[];
    follow_ups: { what: string; with_whom: string | null; when: string | null; contact: string | null }[];
    restrictions: string[];
  };
}

// Mirrors backend/app/schemas.py. If you change one, change the other.
export type Status = "new" | "changed" | "continue" | "stop";
export type Category = "medications" | "follow_ups" | "warning_signs" | "restrictions";

interface Verified {
  source_quote: string;
  grounded: boolean;
  needs_confirmation: boolean;
  issues: string[];
  patient_confirmed: boolean;
}
export interface Medication extends Verified {
  name: string; dose: string | null; route: string | null; frequency: string | null;
  duration: string | null; purpose: string | null; instructions: string | null; status: Status;
}
export interface FollowUp extends Verified { what: string; with_whom: string | null; when: string | null }
export interface WarningSign extends Verified { symptom: string; action: string }
export interface Restriction extends Verified { category: "diet" | "activity" | "wound_care" | "other"; instruction: string }
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
export interface AppConfig { demo: boolean; languages: Record<string, string> }

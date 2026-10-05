"use client";
import { useState } from "react";
import type { AnyItem, Category, Medication, FollowUp, WarningSign, Restriction } from "@/lib/types";

export type Field = {
  key: string; label: string; required?: boolean;
  options?: [value: string, label: string][]; allowEmpty?: boolean;
};

// Standard clinical route-of-administration terms (abbreviation in brackets, as clinicians write them).
export const ROUTE_LABEL: Record<string, string> = {
  oral: "Oral (PO)", sublingual: "Sublingual (SL)", inhaled: "Inhaled", topical: "Topical",
  ophthalmic: "Ophthalmic (eye)", otic: "Otic (ear)", nasal: "Nasal", rectal: "Rectal (PR)",
  subcutaneous: "Subcutaneous (SC)", intramuscular: "Intramuscular (IM)", intravenous: "Intravenous (IV)", other: "Other",
};
const ROUTE_OPTIONS = Object.entries(ROUTE_LABEL) as [string, string][];

const CATEGORY_LABEL: Record<string, string> = {
  diet: "DIET", activity: "ACTIVITY", wound_care: "WOUND CARE", monitoring: "MONITORING",
  medication_limit: "LIMIT", other: "OTHER",
};
const CATEGORY_OPTIONS = Object.entries(CATEGORY_LABEL).map(([v, l]) => [v, l.charAt(0) + l.slice(1).toLowerCase()]) as [string, string][];

export const FIELDS: Record<Category, Field[]> = {
  medications: [
    { key: "name", label: "Medicine", required: true }, { key: "dose", label: "Dose" },
    { key: "previous_dose", label: "Previous dose (only if it changed)" },
    { key: "route", label: "Route", options: ROUTE_OPTIONS, allowEmpty: true },
    { key: "frequency", label: "How often" }, { key: "duration", label: "For how long (without the word “for”)" },
    { key: "purpose", label: "Why you take it (only if your paper says)" },
    { key: "instructions", label: "Special instructions" },
    { key: "status", label: "Status", options: [["new", "New"], ["changed", "Changed"], ["continue", "Continue"], ["stop", "Stop"]] },
  ],
  follow_ups: [
    { key: "what", label: "What", required: true }, { key: "with_whom", label: "With whom" },
    { key: "when", label: "When" }, { key: "contact", label: "Phone number or how to book" },
  ],
  warning_signs: [{ key: "symptom", label: "Warning sign", required: true }, { key: "action", label: "What to do (for example: Call 911)" }],
  restrictions: [
    { key: "category", label: "Type", options: CATEGORY_OPTIONS },
    { key: "instruction", label: "Instruction", required: true },
  ],
};

/** Values a brand-new item starts with in the "add something we missed" form. */
export const NEW_ITEM_DEFAULTS: Record<Category, Record<string, string>> = {
  medications: { status: "new" }, follow_ups: {}, warning_signs: { action: "Call your doctor" }, restrictions: { category: "other" },
};

const STATUS_LABEL: Record<string, string> = { new: "NEW", changed: "CHANGED", continue: "KEEP TAKING", stop: "STOP" };

export function describe(category: Category, item: AnyItem): { title: string; lines: string[]; badge?: string; tone?: string } {
  if (category === "medications") {
    const m = item as Medication;
    const dose = m.dose && m.previous_dose ? `${m.dose} (was ${m.previous_dose})` : m.dose;
    const how = [dose, m.route && ROUTE_LABEL[m.route], m.frequency, m.duration && `for ${m.duration}`].filter(Boolean).join(" · ");
    return {
      title: m.name,
      lines: [how || (m.status === "stop" ? "Do not take this medicine." : "No dose or schedule found"),
              m.purpose ? `Why: ${m.purpose}` : "", m.instructions ?? ""].filter(Boolean),
      badge: STATUS_LABEL[m.status], tone: m.status === "stop" ? "danger" : m.status,
    };
  }
  if (category === "follow_ups") {
    const f = item as FollowUp;
    return { title: f.what, lines: [[f.with_whom, f.when].filter(Boolean).join(" · "), f.contact ? `Contact: ${f.contact}` : ""].filter(Boolean) };
  }
  if (category === "warning_signs") {
    const w = item as WarningSign;
    return { title: w.symptom, lines: [w.action], tone: w.action.includes("911") ? "danger" : undefined,
      badge: w.action.includes("911") ? "911" : undefined };
  }
  const r = item as Restriction;
  return { title: r.instruction, lines: [], badge: CATEGORY_LABEL[r.category] ?? "OTHER" };
}

/** The small form used both for editing an item and for adding a missed one. */
export function ItemForm({ category, values, onChange, onSave, onCancel, saveLabel }: {
  category: Category; values: Record<string, string>; onChange: (v: Record<string, string>) => void;
  onSave: () => void; onCancel: () => void; saveLabel: string;
}) {
  const missing = FIELDS[category].some((f) => f.required && !(values[f.key] ?? "").trim());
  return (
    <div className="form" onClick={(e) => e.stopPropagation()}>
      {FIELDS[category].map((f) => (
        <label key={f.key}>{f.label}{f.required ? " *" : ""}
          {f.options ? (
            <select value={values[f.key] ?? ""} onChange={(e) => onChange({ ...values, [f.key]: e.target.value })}>
              {f.allowEmpty && <option value="">Not stated</option>}
              {f.options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          ) : (
            <input value={values[f.key] ?? ""} onChange={(e) => onChange({ ...values, [f.key]: e.target.value })} />
          )}
        </label>
      ))}
      <div className="row">
        <button className="btn primary" disabled={missing} onClick={onSave}>{saveLabel}</button>
        <button className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

export function valuesToPatch(category: Category, values: Record<string, string>): Record<string, string | null> {
  const patch: Record<string, string | null> = {};
  for (const f of FIELDS[category]) {
    const v = (values[f.key] ?? "").trim();
    patch[f.key] = v === "" ? null : v;
  }
  return patch;
}

interface Props {
  category: Category; item: AnyItem; selected: boolean;
  onSelect: () => void; onConfirm: () => void; onRemove: () => void; onSave: (patch: Record<string, string | null>) => void;
}

export default function ItemCard({ category, item, selected, onSelect, onConfirm, onRemove, onSave }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const d = describe(category, item);
  const added = item.source_quote === "";
  const needsCheck = item.needs_confirmation && !item.patient_confirmed;
  const state = needsCheck ? "check" : item.patient_confirmed ? "confirmed" : "ok";

  function startEdit() {
    const start: Record<string, string> = {};
    for (const f of FIELDS[category]) start[f.key] = String((item as unknown as Record<string, unknown>)[f.key] ?? "");
    setDraft(start); setEditing(true);
  }

  return (
    <article className={`item ${state} ${selected ? "selected" : ""}`} onClick={onSelect}>
      <header>
        <h3>{d.title}</h3>
        {d.badge && <span className={`badge ${d.tone ?? ""}`}>{d.badge}</span>}
      </header>

      {!editing && d.lines.map((l, i) => <p key={i} className="detail">{l}</p>)}

      {editing && (
        <ItemForm category={category} values={draft} onChange={setDraft} saveLabel="Save changes"
          onSave={() => { onSave(valuesToPatch(category, draft)); setEditing(false); }}
          onCancel={() => setEditing(false)} />
      )}

      <p className={`status ${state}`}>
        {state === "check" && <>⚠ Please check this one. {item.issues.join(" ")}</>}
        {state === "confirmed" && <>✔ {added ? "Added by you. This is not from your paper." : "You confirmed this."}</>}
        {state === "ok" && <>✔ Found in your paper.</>}
      </p>

      {!editing && (
        <div className="row" onClick={(e) => e.stopPropagation()}>
          {needsCheck && <button className="btn primary" onClick={onConfirm}>This is right</button>}
          <button className="btn" onClick={startEdit}>Edit</button>
          <button className="btn quiet" onClick={onRemove}>Remove</button>
        </div>
      )}
    </article>
  );
}

"use client";
import { useState } from "react";
import type { AnyItem, Category, Medication, FollowUp, WarningSign, Restriction } from "@/lib/types";

type Field = { key: string; label: string; options?: [value: string, label: string][]; allowEmpty?: boolean };

// Standard clinical route-of-administration terms (abbreviation in brackets, as clinicians write them).
export const ROUTE_LABEL: Record<string, string> = {
  oral: "Oral (PO)", sublingual: "Sublingual (SL)", inhaled: "Inhaled", topical: "Topical",
  ophthalmic: "Ophthalmic (eye)", otic: "Otic (ear)", nasal: "Nasal", rectal: "Rectal (PR)",
  subcutaneous: "Subcutaneous (SC)", intramuscular: "Intramuscular (IM)", intravenous: "Intravenous (IV)", other: "Other",
};
const ROUTE_OPTIONS = Object.entries(ROUTE_LABEL) as [string, string][];

const FIELDS: Record<Category, Field[]> = {
  medications: [
    { key: "name", label: "Medicine" }, { key: "dose", label: "Dose" }, { key: "route", label: "Route", options: ROUTE_OPTIONS, allowEmpty: true },
    { key: "frequency", label: "How often" }, { key: "duration", label: "For how long" },
    { key: "instructions", label: "Special instructions" },
    { key: "status", label: "Status", options: [["new", "New"], ["changed", "Changed"], ["continue", "Continue"], ["stop", "Stop"]] },
  ],
  follow_ups: [{ key: "what", label: "What" }, { key: "with_whom", label: "With whom" }, { key: "when", label: "When" }],
  warning_signs: [{ key: "symptom", label: "Warning sign" }, { key: "action", label: "What to do" }],
  restrictions: [{ key: "instruction", label: "Instruction" }],
};

const STATUS_LABEL: Record<string, string> = { new: "NEW", changed: "CHANGED", continue: "KEEP TAKING", stop: "STOP" };

export function describe(category: Category, item: AnyItem): { title: string; lines: string[]; badge?: string; tone?: string } {
  if (category === "medications") {
    const m = item as Medication;
    const how = [m.dose, m.route && ROUTE_LABEL[m.route], m.frequency, m.duration && `for ${m.duration}`].filter(Boolean).join(" · ");
    return { title: m.name, lines: [how || "No dose or schedule found", m.instructions ?? ""].filter(Boolean),
      badge: STATUS_LABEL[m.status], tone: m.status === "stop" ? "danger" : m.status };
  }
  if (category === "follow_ups") {
    const f = item as FollowUp;
    return { title: f.what, lines: [[f.with_whom, f.when].filter(Boolean).join(" · ")].filter(Boolean) };
  }
  if (category === "warning_signs") {
    const w = item as WarningSign;
    return { title: w.symptom, lines: [w.action], tone: w.action.includes("911") ? "danger" : undefined,
      badge: w.action.includes("911") ? "911" : undefined };
  }
  const r = item as Restriction;
  return { title: r.instruction, lines: [], badge: r.category.replace("_", " ").toUpperCase() };
}

interface Props {
  category: Category; item: AnyItem; selected: boolean;
  onSelect: () => void; onConfirm: () => void; onRemove: () => void; onSave: (patch: Record<string, string | null>) => void;
}

export default function ItemCard({ category, item, selected, onSelect, onConfirm, onRemove, onSave }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const d = describe(category, item);
  const needsCheck = item.needs_confirmation && !item.patient_confirmed;
  const state = needsCheck ? "check" : item.patient_confirmed ? "confirmed" : "ok";

  function startEdit() {
    const start: Record<string, string> = {};
    for (const f of FIELDS[category]) start[f.key] = String((item as unknown as Record<string, unknown>)[f.key] ?? "");
    setDraft(start); setEditing(true);
  }

  function save() {
    const patch: Record<string, string | null> = {};
    for (const f of FIELDS[category]) patch[f.key] = draft[f.key].trim() === "" ? null : draft[f.key].trim();
    onSave(patch); setEditing(false);
  }

  return (
    <article className={`item ${state} ${selected ? "selected" : ""}`} onClick={onSelect}>
      <header>
        <h3>{d.title}</h3>
        {d.badge && <span className={`badge ${d.tone ?? ""}`}>{d.badge}</span>}
      </header>

      {!editing && d.lines.map((l, i) => <p key={i} className="detail">{l}</p>)}

      {editing && (
        <div className="form" onClick={(e) => e.stopPropagation()}>
          {FIELDS[category].map((f) => (
            <label key={f.key}>{f.label}
              {f.options ? (
                <select value={draft[f.key]} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}>
                  {f.allowEmpty && <option value="">Not stated</option>}
                  {f.options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              ) : (
                <input value={draft[f.key]} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
              )}
            </label>
          ))}
          <div className="row">
            <button className="btn primary" onClick={save}>Save changes</button>
            <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      )}

      <p className={`status ${state}`}>
        {state === "check" && <>⚠ Please check this one. {item.issues.join(" ")}</>}
        {state === "confirmed" && <>✔ You confirmed this.</>}
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

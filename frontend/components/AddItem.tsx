"use client";
import { useState } from "react";
import { ItemForm, NEW_ITEM_DEFAULTS, valuesToPatch } from "./ItemCard";
import type { AnyItem, Category } from "@/lib/types";

const LABEL: Record<Category, string> = {
  medications: "a medicine", follow_ups: "an appointment or test", warning_signs: "a warning sign", restrictions: "an instruction",
};

/** Items the AI missed can be added by the patient. They carry no quote from the paper and say so. */
export default function AddItem({ category, onAdd }: { category: Category; onAdd: (item: AnyItem) => void }) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>(NEW_ITEM_DEFAULTS[category]);

  function save() {
    const patch = valuesToPatch(category, values);
    if (category === "warning_signs" && !patch.action) patch.action = "Call your doctor";
    const item = {
      ...patch,
      source_quote: "", grounded: false, needs_confirmation: true, issues: ["Added by you."], patient_confirmed: true,
    } as unknown as AnyItem;
    onAdd(item);
    setOpen(false); setValues(NEW_ITEM_DEFAULTS[category]);
  }

  if (!open) {
    return <button className="btn quiet add-item" onClick={() => setOpen(true)}>+ Add {LABEL[category]} we missed</button>;
  }
  return (
    <div className="item confirmed">
      <h3>Add {LABEL[category]}</h3>
      <p className="small">Only add what is written on your paper. We will mark it as added by you.</p>
      <ItemForm category={category} values={values} onChange={setValues} saveLabel="Add" onSave={save}
        onCancel={() => { setOpen(false); setValues(NEW_ITEM_DEFAULTS[category]); }} />
    </div>
  );
}

"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import AddItem from "./AddItem";
import ItemCard from "./ItemCard";
import { findQuote } from "@/lib/highlight";
import type { AnyItem, AppConfig, Category, ExtractionResult } from "@/lib/types";

const SECTIONS: { key: Category; title: string }[] = [
  { key: "medications", title: "Medicines" },
  { key: "follow_ups", title: "Appointments and tests" },
  { key: "warning_signs", title: "Warning signs" },
  { key: "restrictions", title: "Daily care at home" },
];

interface Props {
  extraction: ExtractionResult;
  config: AppConfig;
  busy: boolean;
  error: string | null;
  onChange: (ex: ExtractionResult) => void;
  onBack: () => void;
  onMakePlan: (opts: { language: string; reading_level: string; acknowledged_unclear: boolean; acknowledged_review: boolean }) => void;
}

export default function ConfirmStep({ extraction: ex, config, busy, error, onChange, onBack, onMakePlan }: Props) {
  const [selected, setSelected] = useState<{ cat: Category; idx: number } | null>(null);
  const [ack, setAck] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [language, setLanguage] = useState("en");
  const [level, setLevel] = useState("simple");
  const markRef = useRef<HTMLElement>(null);

  const items = (cat: Category) => ex[cat] as AnyItem[];
  const all = SECTIONS.flatMap((s) => items(s.key));
  const remaining = all.filter((i) => i.needs_confirmation && !i.patient_confirmed).length;
  const needAck = ex.unclear_items.length > 0 && !ack;
  const canMake = remaining === 0 && !needAck && reviewed && all.length > 0 && !busy;

  const range = useMemo(() => {
    if (!selected) return null;
    const item = items(selected.cat)[selected.idx];
    return item ? findQuote(ex.document_text, item.source_quote) : null;
  }, [selected, ex]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { markRef.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [range]);

  function update(cat: Category, fn: (list: AnyItem[]) => AnyItem[]) {
    const next = { ...ex, [cat]: fn(items(cat)) } as ExtractionResult;
    next.total_items = SECTIONS.reduce((n, s) => n + (next[s.key] as AnyItem[]).length, 0);
    next.items_needing_confirmation = SECTIONS.flatMap((s) => next[s.key] as AnyItem[])
      .filter((i) => i.needs_confirmation && !i.patient_confirmed).length;
    onChange(next);
  }

  const paper = ex.document_text;
  return (
    <div>
      <button className="btn quiet" onClick={onBack}>← Start over</button>
      <h1>Check what we understood</h1>
      <p className="lead">
        {remaining > 0
          ? <><strong>{remaining} item{remaining > 1 ? "s" : ""}</strong> {remaining > 1 ? "need" : "needs"} your check before we can make your plan.</>
          : <>Our checker found nothing wrong, but it can only tell that the words exist in your paper, not that they mean what we think. <strong>Please read each item against your paper yourself.</strong></>}
        {" "}Tap an item to see where it came from in your paper.
      </p>

      <div className="two-col">
        <section className="paper card" aria-label="Your paper">
          <h2>Your paper</h2>
          <pre>
            {range ? (
              <>
                {paper.slice(0, range[0])}
                <mark ref={markRef}>{paper.slice(range[0], range[1])}</mark>
                {paper.slice(range[1])}
              </>
            ) : paper}
          </pre>
        </section>

        <div>
          {SECTIONS.map(({ key, title }) => (
            <section key={key}>
              <h2>{title}</h2>
              {items(key).map((item, idx) => (
                <ItemCard
                  key={`${key}-${idx}-${item.source_quote}`}
                  category={key} item={item}
                  selected={selected?.cat === key && selected.idx === idx}
                  onSelect={() => setSelected({ cat: key, idx })}
                  onConfirm={() => update(key, (l) => l.map((x, i) => (i === idx ? { ...x, patient_confirmed: true } : x)))}
                  onRemove={() => { setSelected(null); update(key, (l) => l.filter((_, i) => i !== idx)); }}
                  onSave={(patch) => update(key, (l) => l.map((x, i) => (i === idx ? { ...x, ...patch, patient_confirmed: true } : x)))}
                />
              ))}
              <AddItem category={key} onAdd={(item) => update(key, (l) => [...l, item])} />
            </section>
          ))}

          {ex.unclear_items.length > 0 && (
            <section className="card notice">
              <h2>Please check with your care team</h2>
              <ul>{ex.unclear_items.map((u) => <li key={u}>{u}</li>)}</ul>
              <label className="check">
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                I have read this.
              </label>
            </section>
          )}

          <section className="card">
            <h2>Make my plan</h2>
            <label className="check">
              <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
              I compared this list with my paper. It is correct, or I fixed what was wrong.
            </label>
            <div className="form">
              <label>Language
                <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  {Object.entries(config.languages).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                </select>
              </label>
              <label>Wording
                <select value={level} onChange={(e) => setLevel(e.target.value)}>
                  <option value="simple">Very simple</option>
                  <option value="standard">Standard</option>
                </select>
              </label>
            </div>
            {!canMake && !busy && (
              <p className="small" role="status">
                {remaining > 0 ? "Check the highlighted items first. " : ""}
                {needAck ? "Tick “I have read this” above. " : ""}
                {!reviewed ? "Tick the box to say you compared the list with your paper. " : ""}
                {all.length === 0 ? "There are no items left." : ""}
              </p>
            )}
            <button className="btn primary big" disabled={!canMake}
              onClick={() => onMakePlan({ language, reading_level: level, acknowledged_unclear: ack, acknowledged_review: reviewed })}>
              {busy ? "Writing your plan…" : "Make my plan"}
            </button>
            {error && <p role="alert" className="error">{error}</p>}
          </section>
        </div>
      </div>
    </div>
  );
}

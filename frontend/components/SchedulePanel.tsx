import type { DailySchedule } from "@/lib/types";

function clock(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

export default function SchedulePanel({ schedule }: { schedule: DailySchedule | null }) {
  if (!schedule) {
    return (
      <section className="card notice" dir="ltr" lang="en">
        <h2>Your day</h2><p>We could not build your daily schedule this time. Please follow your paper.</p>
      </section>
    );
  }
  const { slots, as_needed, tapers, unscheduled } = schedule;
  if (!slots.length && !as_needed.length && !tapers.length && !unscheduled.length) return null;
  const overnight = slots.filter((s) => s.label === "Overnight").flatMap((s) => s.items.map((i) => i.name));
  return (
    <section className="card" dir="ltr" lang="en">
      <h2>Your day</h2>
      {overnight.length > 0 && (
        <p className="finding">
          <strong>Overnight dose:</strong> your paper says to take {[...new Set(overnight)].join(", ")} at regular
          hours, which includes the night. Ask your care team if you should wake up for it.
        </p>
      )}
      {slots.length > 0 && (
        <>
          <p className="small">Suggested times. You can move them to fit your routine; keep the spacing your paper asks for.</p>
          {slots.map((s) => (
            <div key={s.time} className="slot">
              <div className="when"><strong>{clock(s.time)}</strong><span>{s.label}</span></div>
              <ul>
                {s.items.map((i, n) => (
                  <li key={`${i.name}-${n}`}>
                    <strong>{i.name}</strong> {i.dose}
                    {i.note && <span className="small"> · {i.note}</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      )}
      {tapers.map((t) => (
        <div key={t.name} className="slot">
          <div className="when"><strong>{t.name}</strong><span>step-down</span></div>
          <ul>
            {t.steps.map((st) => <li key={st.when}><strong>{st.when}:</strong> {st.dose}</li>)}
            {t.after && <li>{t.after}</li>}
            {t.note && <li className="small">{t.note}</li>}
          </ul>
        </div>
      ))}
      {as_needed.length > 0 && (
        <div className="slot">
          <div className="when"><strong>Only when needed</strong></div>
          <ul>
            {as_needed.map((a) => (
              <li key={a.name}><strong>{a.name}</strong> {a.dose}
                <span className="small"> · {[a.how_often, a.note].filter(Boolean).join("; ")}</span></li>
            ))}
          </ul>
        </div>
      )}
      {unscheduled.length > 0 && (
        <div className="finding">
          <strong>Ask your care team about timing</strong>
          <ul>{unscheduled.map((u) => <li key={u.name}><strong>{u.name}:</strong> {u.reason}</li>)}</ul>
        </div>
      )}
    </section>
  );
}

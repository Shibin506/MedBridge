/** "just now", "12 min ago", "3 h ago", "2 days ago". Empty for a missing or unreadable time. */
export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return "";
  const min = Math.max(0, Math.round((now - t) / 60000));
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

export function clockTime(iso: string | null | undefined): string {
  const t = iso ? new Date(iso) : null;
  return t && !Number.isNaN(t.getTime()) ? t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
}

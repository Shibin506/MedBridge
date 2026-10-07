export default function WeightChart({ points }: { points: { day: number; pounds: number }[] }) {
  if (points.length === 0) return <p className="small">No weights yet. They appear after the first check-in.</p>;
  const w = 300, h = 110, pad = 26;
  const xs = points.map((p) => p.day), ys = points.map((p) => p.pounds);
  const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1);
  const y0 = Math.min(...ys) - 2, y1 = Math.max(...ys) + 2;
  const sx = (d: number) => pad + ((d - x0) / (x1 - x0)) * (w - 2 * pad);
  const sy = (v: number) => h - pad - ((v - y0) / (y1 - y0)) * (h - 2 * pad);
  return (
    <>
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Weight by day: ${points.map((p) => `day ${p.day} ${p.pounds} pounds`).join(", ")}`} className="chart">
        <polyline fill="none" stroke="var(--brand)" strokeWidth="2.5" points={points.map((p) => `${sx(p.day)},${sy(p.pounds)}`).join(" ")} />
        {points.map((p) => (
          <g key={p.day}>
            <circle cx={sx(p.day)} cy={sy(p.pounds)} r="4" fill="var(--brand)" />
            <text x={sx(p.day)} y={sy(p.pounds) - 8} textAnchor="middle" fontSize="10" fill="currentColor">{p.pounds}</text>
            <text x={sx(p.day)} y={h - 8} textAnchor="middle" fontSize="10" fill="currentColor">D{p.day}</text>
          </g>
        ))}
      </svg>
    </>
  );
}

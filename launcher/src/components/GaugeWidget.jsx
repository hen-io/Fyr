import { usePolledFetch } from "../hooks/usePolledFetch.js";

// A single ratio against a limit is a Meter, not a needle dial (see the
// dataviz skill's choosing-a-form guidance) - this is a meter bent into a
// 270-degree arc so it still reads as a "gauge" without the accuracy
// problems of a needle. Fill color is severity (normal -> warning ->
// critical), the track is the same look at low opacity - both fixed,
// never themed by the app's decorative palette, per the skill's status-color
// rule ("never reused for series N", i.e. never tied to --accent).
const SEVERITY_COLORS = {
  normal: "#3987e5",
  warning: "#fab219",
  critical: "#d03b3b",
};

function severityFor(value, warningAbove, criticalAbove) {
  if (value == null) return "normal";
  if (criticalAbove != null && value >= criticalAbove) return "critical";
  if (warningAbove != null && value >= warningAbove) return "warning";
  return "normal";
}

const RADIUS = 40;
const STROKE_WIDTH = 10;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const SWEEP = 0.75; // 270 of 360 degrees - the classic open-bottom gauge shape

export function GaugeWidget({ id, label, unit, min = 0, max = 100, warningAbove, criticalAbove, pollMs = 30000 }) {
  const data = usePolledFetch(`/api/widget/${id}`, pollMs);
  const value = data?.value ?? null;

  const clamped = value == null ? min : Math.min(max, Math.max(min, value));
  const fraction = max > min ? (clamped - min) / (max - min) : 0;

  const trackDash = `${SWEEP * CIRCUMFERENCE} ${(1 - SWEEP) * CIRCUMFERENCE}`;
  const fillDash = `${fraction * SWEEP * CIRCUMFERENCE} ${CIRCUMFERENCE - fraction * SWEEP * CIRCUMFERENCE}`;
  const fillColor = SEVERITY_COLORS[severityFor(value, warningAbove, criticalAbove)];

  return (
    <div
      className="glass-light"
      style={{ width: 150, padding: 14, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}
      title={value != null ? `${label}: ${value}${unit || ""}` : `${label}: ingen data`}
    >
      <svg viewBox="0 0 100 100" width={100} height={100}>
        <circle
          cx="50"
          cy="50"
          r={RADIUS}
          fill="none"
          stroke="rgba(255,255,255,0.14)"
          strokeWidth={STROKE_WIDTH}
          strokeDasharray={trackDash}
          strokeLinecap="round"
          transform="rotate(135 50 50)"
        />
        <circle
          cx="50"
          cy="50"
          r={RADIUS}
          fill="none"
          stroke={fillColor}
          strokeWidth={STROKE_WIDTH}
          strokeDasharray={fillDash}
          strokeLinecap="round"
          transform="rotate(135 50 50)"
          style={{ transition: "stroke-dasharray 0.6s ease, stroke 0.3s ease" }}
        />
        <text x="50" y="47" textAnchor="middle" fontSize="20" fontWeight="700" fill="var(--text)">
          {value != null ? Math.round(value * 10) / 10 : "–"}
        </text>
        <text x="50" y="63" textAnchor="middle" fontSize="10" fill="var(--text)" opacity="0.7">
          {unit || ""}
        </text>
      </svg>
      <span style={{ fontSize: "0.8rem", opacity: 0.85, textAlign: "center" }}>{label}</span>
    </div>
  );
}

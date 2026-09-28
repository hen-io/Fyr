import { GaugeWidget } from "./GaugeWidget.jsx";

// Renders whatever widgets are configured (backend-data/ui.conf). Only
// "gauge" exists today - an unknown/future type is silently skipped rather
// than rendering something broken.
export function WidgetPanel({ widgets }) {
  const gauges = widgets.filter((w) => w.type === "gauge");
  if (gauges.length === 0) return null;

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 16, justifyContent: "center", marginBottom: 24 }}>
      {gauges.map((w) => (
        <GaugeWidget
          key={w.id}
          id={w.id}
          label={w.label}
          unit={w.unit}
          min={w.min}
          max={w.max}
          warningAbove={w.warning_above}
          criticalAbove={w.critical_above}
        />
      ))}
    </div>
  );
}

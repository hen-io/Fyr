import { useCalendar } from "../hooks/useCalendar.js";

function formatEvent(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const isAllDay = iso.length === 10; // "YYYY-MM-DD" with no time component
  const dateLabel = new Intl.DateTimeFormat("nb-NO", { day: "numeric", month: "short" }).format(date);
  if (isAllDay) return dateLabel;
  const timeLabel = new Intl.DateTimeFormat("nb-NO", { hour: "2-digit", minute: "2-digit" }).format(date);
  return `${dateLabel} ${timeLabel}`;
}

// Renders nothing at all when no calendar is configured or there are no
// upcoming events - this is meant to disappear cleanly rather than show an
// empty card.
export function CalendarPanel() {
  const events = useCalendar();
  if (events.length === 0) return null;

  return (
    <div
      className="glass-light"
      style={{ padding: "12px 16px", marginBottom: 24, maxWidth: 360, marginInline: "auto" }}
    >
      <div style={{ fontSize: "0.8rem", opacity: 0.7, marginBottom: 8 }}>Kommende</div>
      {events.map((event, i) => (
        <div
          key={`${event.title}-${event.start}-${i}`}
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            padding: "4px 0",
            fontSize: "0.9rem",
          }}
        >
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{event.title}</span>
          <span style={{ opacity: 0.7, flexShrink: 0 }}>{formatEvent(event.start)}</span>
        </div>
      ))}
    </div>
  );
}

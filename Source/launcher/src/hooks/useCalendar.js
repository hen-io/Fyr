import { usePolledFetch } from "./usePolledFetch.js";

// Backed by /api/calendar/upcoming - a no-op (returns nothing) until
// HA_CALENDAR_ENTITY is set in the backend's .env. Polled every 10 minutes;
// calendars don't change fast enough to justify anything shorter.
export function useCalendar() {
  const data = usePolledFetch("/api/calendar/upcoming", 600000);
  return Array.isArray(data) ? data : [];
}

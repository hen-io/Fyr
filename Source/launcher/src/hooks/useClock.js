import { useEffect, useState } from "react";

export function useClock() {
  const [time, setTime] = useState("");
  const [date, setDate] = useState("");

  useEffect(() => {
    const update = () => {
      const now = new Date();
      setTime(`${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`);
      setDate(new Intl.DateTimeFormat("nb-NO", { day: "numeric", month: "long", year: "numeric" }).format(now));
    };

    update();
    const interval = setInterval(update, 1000 * 3);
    return () => clearInterval(interval);
  }, []);

  return { time, date };
}

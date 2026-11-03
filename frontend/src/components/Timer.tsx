import { useEffect, useState } from "react";
import { TimerState } from "../ws";

export interface TimerSnapshot {
  state: TimerState;
  /** Time left when the server sent this snapshot. */
  remainingMs: number;
  /** `performance.now()` when it arrived; the countdown runs locally from there. */
  receivedAt: number;
}

function format(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function Timer({ timer }: { timer: TimerSnapshot | null }) {
  const [, setNow] = useState(0);
  const counting = timer !== null && (timer.state === "running" || timer.state === "warning");

  useEffect(() => {
    if (!counting) return;
    const id = window.setInterval(() => setNow(performance.now()), 250);
    return () => window.clearInterval(id);
  }, [counting]);

  if (!timer) return <span className="timer">--:--</span>;
  const remaining = counting ? timer.remainingMs - (performance.now() - timer.receivedAt) : 0;
  const note =
    timer.state === "warning"
      ? "5 minutes left"
      : timer.state === "time_up"
        ? "Time is up"
        : null;
  return (
    <>
      {note && <span className="timer-note">{note}</span>}
      <span className={`timer ${timer.state}`}>{format(remaining)}</span>
    </>
  );
}

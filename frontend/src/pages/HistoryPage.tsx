import { useEffect, useState } from "react";
import { HistoryRow, listSessions } from "../api";
import { clock } from "../replay";

export function HistoryPage() {
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSessions()
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  return (
    <main className="history">
      <p>
        <a href="#/">New interview</a>
      </p>
      <h1>History</h1>
      {error && <p className="error">{error}</p>}
      {!rows ? (
        !error && <p>Loading…</p>
      ) : rows.length === 0 ? (
        <p className="hint">No Sessions yet.</p>
      ) : (
        <table className="rubric">
          <thead>
            <tr>
              <th>Problem</th>
              <th>Date</th>
              <th>Duration</th>
              <th>Overall Signal</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <a
                    href={
                      row.status === "live" ? `#/sessions/${row.id}` : `#/sessions/${row.id}/report`
                    }
                  >
                    {row.title}
                  </a>
                  {row.status === "live" && <span className="hint"> (in progress)</span>}
                  {row.status === "abandoned" && <span className="hint"> (abandoned)</span>}
                </td>
                <td>{new Date(row.created_at).toLocaleString()}</td>
                <td>{clock(row.duration_ms)}</td>
                <td>
                  {row.overall_signal ? (
                    <span
                      className={`signal-label signal-${row.overall_signal.replace(/ /g, "-").toLowerCase()}`}
                    >
                      {row.overall_signal}
                    </span>
                  ) : (
                    <span className="hint">{row.status === "live" ? "–" : "No report"}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

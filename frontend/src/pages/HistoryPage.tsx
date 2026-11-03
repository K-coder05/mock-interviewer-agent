import { useEffect, useState } from "react";
import { HistoryRow, deleteSession, exportUrl, listSessions, regenerateReport } from "../api";
import { clock } from "../replay";

export function HistoryPage() {
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSessions()
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : String(err));

  const remove = (row: HistoryRow) => {
    if (!window.confirm(`Delete "${row.title}" with its transcript, code and report? This cannot be undone.`))
      return;
    deleteSession(row.id)
      .then(() => {
        setError(null);
        setRows((current) => current && current.filter((r) => r.id !== row.id));
      })
      .catch(fail);
  };

  const regenerate = (row: HistoryRow) => {
    regenerateReport(row.id)
      .then(() => {
        window.location.hash = `#/sessions/${row.id}/report`;
      })
      .catch(fail);
  };

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
              <th></th>
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
                <td className="row-actions">
                  <a href={exportUrl(row.id)} download>
                    Export
                  </a>
                  {row.status !== "live" && (
                    <>
                      {" "}
                      <button type="button" onClick={() => regenerate(row)}>
                        {row.overall_signal ? "Regenerate report" : "Generate report"}
                      </button>
                    </>
                  )}{" "}
                  <button type="button" disabled={row.status === "live"} onClick={() => remove(row)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

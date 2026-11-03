// REST client for Session lifecycle and reads.

export interface SessionEvent {
  id: string;
  session_id: string;
  seq: number;
  t_ms: number;
  type: string;
  payload: Record<string, unknown>;
}

export interface SessionInfo {
  id: string;
  created_at: string;
  ended_at: string | null;
  title: string;
  problem_md: string;
  starter_code: string | null;
  settings: { duration_min: number; autocomplete: boolean; models: Record<string, string> };
  status: "live" | "ended" | "abandoned" | "report_ready" | "report_failed";
}

export interface CreateSessionInput {
  problem_md: string;
  starter_code?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // keep statusText
    }
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export function createSession(input: CreateSessionInput): Promise<{ session_id: string }> {
  return request("/api/sessions", { method: "POST", body: JSON.stringify(input) });
}

export function getSession(id: string): Promise<{ session: SessionInfo; events: SessionEvent[] }> {
  return request(`/api/sessions/${encodeURIComponent(id)}`);
}

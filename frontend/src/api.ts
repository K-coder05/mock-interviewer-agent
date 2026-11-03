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
  settings: {
    duration_min: number;
    autocomplete: boolean;
    style: StyleSetting;
    models: Record<string, string>;
  };
  status: "live" | "ended" | "abandoned" | "report_ready" | "report_failed";
}

export type StyleSetting = { preset: string } | { custom: string };

export const STYLE_PRESETS: { id: string; label: string }[] = [
  { id: "faang_standard", label: "FAANG standard" },
  { id: "friendly_new_grad", label: "Friendly new-grad" },
  { id: "pragmatic_startup", label: "Pragmatic startup" },
];

export interface CreateSessionInput {
  problem_md: string;
  starter_code?: string;
  private_notes?: string;
  style: StyleSetting;
  duration_min: number;
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

export interface Evidence {
  t_ms: number;
  quote_or_code: string;
  comment: string;
}

export interface RubricRow {
  dimension: string;
  label: string;
  weight: number;
  score: 1 | 2 | 3 | 4;
  evidence: Evidence[];
  note: string | null;
}

export interface CandidateTest {
  id: string;
  kind: "executed" | "traced";
  form: "assert" | "call" | "printed_call" | "stdin" | "traced";
  input: string;
  verified: boolean;
  outcome: "ok" | "failed" | "unknown" | null;
  expected_result: string | null;
  category: string;
  t_ms: number;
  runs: number;
}

export interface TestingBreakdown {
  groups: { category: string; tests: CandidateTest[] }[];
  ran_but_not_verified: CandidateTest[];
  missed_categories: { name: string; description: string }[];
  totals: { executed: number; traced: number; verified: number };
}

export interface Report {
  summary: string;
  overall_signal: {
    label: "Strong No" | "No" | "Lean No" | "Lean Hire" | "Hire" | "Strong Hire";
    weighted_average: number;
    capped: boolean;
    rationale: string;
  };
  rubric: RubricRow[];
  /** Absent on Reports generated before ticket 06. */
  testing?: TestingBreakdown;
  correctness: { executed: false; note: string; snapshot_seq: number | null; t_ms: number | null };
}

export interface ReportUsage {
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
  attempts: number;
}

export type ReportView =
  | {
      status: "report_ready";
      created_at: string;
      model: string;
      metrics: Record<string, number>;
      report: Report;
      usage: ReportUsage | null;
    }
  | { status: "generating" | "live" | "ended" | "abandoned" | "report_failed" };

export function getReport(id: string): Promise<ReportView> {
  return request(`/api/sessions/${encodeURIComponent(id)}/report`);
}

/** Rebuild the Report from the stored events (backs Retry and Generate report). */
export function regenerateReport(id: string): Promise<{ status: "generating" }> {
  return request(`/api/sessions/${encodeURIComponent(id)}/report?regenerate=true`, {
    method: "POST",
  });
}

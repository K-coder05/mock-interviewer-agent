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
    /** Absent on Sessions created before ticket 11; the TTS keys before ticket 12. */
    voice?: VoiceSettings;
  };
  status: "live" | "ended" | "abandoned" | "report_ready" | "report_failed";
}

export interface VoiceSettings {
  utterance_silence_ms: number;
  tts?: "browser" | "off";
  tts_voice?: string | null;
  tts_rate?: number;
  /** Fallback for speakers: stop listening while the Interviewer speaks (no barge-in). */
  pause_stt_during_tts?: boolean;
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
  autocomplete: boolean;
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

export interface Strength {
  title: string;
  detail: string;
}

export interface Improvement extends Strength {
  drill: string;
}

export interface IdealWalkthrough {
  approach: string;
  complexity: string;
  code: string;
}

export interface Metrics {
  duration_ms: number;
  time_to_first_code_ms: number | null;
  time_to_first_run_ms: number | null;
  time_to_first_test_ms: number | null;
  runs: number;
  failed_runs: number;
  error_types: Record<string, number>;
  /** Absent on Reports generated before ticket 08. */
  phase_ms?: Record<string, number>;
  silence_gaps: { start_ms: number; end_ms: number; duration_ms: number }[];
  candidate_words: number;
  interviewer_words: number;
  candidate_talk_ratio: number | null;
  coding_words: number | null;
  coding_words_per_minute: number | null;
  hints_by_level: Record<string, number>;
  large_pastes: { t_ms: number; length: number }[];
  muted_ms: number;
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
  /** The next four are absent on Reports generated before ticket 07. */
  strengths?: Strength[];
  improvements?: Improvement[];
  ideal_walkthrough?: IdealWalkthrough;
  autocomplete?: boolean;
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
      metrics: Partial<Metrics>;
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

export interface HistoryRow {
  id: string;
  title: string;
  created_at: string;
  status: SessionInfo["status"];
  duration_ms: number;
  /** Null while the Session has no Report. */
  overall_signal: Report["overall_signal"]["label"] | null;
}

export function listSessions(): Promise<HistoryRow[]> {
  return request("/api/sessions");
}

export interface TimelineMarker {
  kind: "run" | "hint" | "phase" | "silence";
  t_ms: number;
  /** Silence gaps only. */
  end_ms: number | null;
  label: string;
}

export interface ReplayData {
  session: SessionInfo;
  events: SessionEvent[];
  duration_ms: number;
  markers: TimelineMarker[];
}

export function getReplay(id: string): Promise<ReplayData> {
  return request(`/api/sessions/${encodeURIComponent(id)}/replay`);
}

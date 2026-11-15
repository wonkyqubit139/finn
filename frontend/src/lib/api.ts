// Typed client for the FINN backend. All calls are relative (/api/...).

export type Tier = "high" | "medium" | "routine";

export interface Announcement {
  id: string;
  symbol: string;
  company: string;
  source: string;
  published_at: string;
  subject: string;
  body: string | null;
  headline: string;
  attachment_url: string | null;
  category: string;
  sub_type: string;
  classified_by: string;
  priority: number;
  tier: Tier;
  summary: string | null;
  alerted?: boolean;
  enrichment: ResultsEnrichment | PeopleEnrichment | null;
}

export interface MarketAlert {
  id: number;
  kind: "price" | "volume";
  symbol: string;
  company: string;
  ref: string; // trading date
  message: string;
  value: number;
  threshold: number;
}

export interface DataMode {
  mode: "live" | "snapshot" | "empty";
  detail?: string;
}

export interface Feed {
  window: { key: string; from: string; to: string; label: string };
  data: DataMode;
  market_alerts: MarketAlert[];
  groups: Record<Tier, Announcement[]>;
  counts: Record<string, number>;
  total: number;
}

export interface Eod {
  date: string;
  close: number;
  prev_close: number;
  change_pct: number | null;
  volume: number | null;
  avg_volume: number | null;
  volume_multiple: number | null;
  sessions_in_avg: number;
}

export interface Holding {
  symbol: string;
  name: string;
  sector: string;
  financial: boolean;
  eod: Eod | null;
  spark: number[];
  price_source: string | null;
  notable_7d: number;
  top_filing: { id: string; headline: string; category: string; priority: number; published_at: string } | null;
}

export interface PortfolioResp {
  holdings: Holding[];
  data: DataMode;
  thresholds: { price_move_pct: number; volume_multiple: number };
}

export interface Settings {
  price_move_pct: number;
  volume_multiple: number;
  volume_lookback_days: number;
  watched_categories: string[];
  announcement_alert_min_priority: number;
  last_seen_at: string | null;
}

export interface AlertRow {
  id: number;
  kind: "price" | "volume" | "announcement";
  symbol: string;
  ref: string;
  message: string;
  created_at: string;
  seen: number;
}

export interface SourceRow {
  source: string;
  last_ok: string | null;
  last_error: string | null;
  last_error_at: string | null;
  detail: string | null;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  feed: (window: string) => req<Feed>(`/api/feed?window=${encodeURIComponent(window)}`),
  markSeen: () => req<{ ok: boolean }>("/api/feed/seen", { method: "POST" }),
  portfolio: () => req<PortfolioResp>("/api/portfolio"),
  alerts: () => req<{ alerts: AlertRow[]; unseen: number }>("/api/alerts"),
  alertsSeen: () => req<{ ok: boolean }>("/api/alerts/seen", { method: "POST" }),
  settings: () => req<{ settings: Settings; categories: string[] }>("/api/settings"),
  saveSettings: (s: Partial<Settings>) =>
    req<{ settings: Settings }>("/api/settings", { method: "PUT", body: JSON.stringify(s) }),
  refresh: () => req<Record<string, unknown>>("/api/refresh", { method: "POST" }),
  sources: () =>
    req<{ sources: SourceRow[]; data: DataMode; counts: { announcements: number; price_rows: number } }>("/api/sources"),
  usage: () =>
    req<{ by_task: { task: string; model: string; calls: number; cache_hits: number; prompt_tokens: number; completion_tokens: number; failures: number }[]; fast_model: string | null; deep_model: string | null }>("/api/llm/usage"),
  health: () => req<{ ok: boolean; llm_fast: boolean; llm_deep: boolean }>("/api/health"),
};

// ---- research ---------------------------------------------------------------------------

export interface Metrics {
  revenue: number | null; ebitda: number | null; pbt: number | null; pat: number | null;
  ebitda_margin: number | null; pat_margin: number | null; ebitda_note?: string;
}
export interface SourceRef { ref?: string | null; page: number | null; url?: string; as?: string }
export interface Check { name: string; ok: boolean; detail: string }

export interface ResultsEnrichment {
  type: "results"; ok: boolean; reason?: string; period_label: string; basis: string; financial: boolean;
  current: Metrics; previous: Metrics | null; year_ago: Metrics | null;
  qoq: Record<string, number | null>; yoy: Record<string, number | null>;
  checks: Check[]; unit_note: string | null; page: number; url: string;
}
export interface PeopleEnrichment {
  type: "people"; ok: boolean; url: string; reason?: string;
  changes: { person: string; role: string; change: string; effective: string | null; reason: string | null;
             background: string | null; quote: string | null; page: number | null }[];
}

export interface Promise_ {
  id: string; quote: string; speaker: string | null; topic: string | null; metric: string; specificity: string;
  ref: string; page: number; said_in: string; url: string;
  status: "delivered" | "missed" | "on_track" | "off_track" | "pending" | "unverifiable";
  period_label: string; target_text: string; actual_text?: string; actual_span?: string; detail?: string | null;
  assessed_by: string; also_said?: { said_in: string; ref: string; page: number }[]; model_verdict?: string; model_reason?: string; model_cite?: string[];
}
export interface Cited { text?: string; point?: string; cite: string[] }
export interface FinRow extends Metrics {
  period_end: string; label: string; revenue_yoy: number | null; pat_yoy: number | null; source: SourceRef;
}
export interface DocRef {
  ref: string; id: string; kind: string; period: string | null; period_label: string | null;
  title: string; url: string; pages: number | null; filed_at: string | null;
}
export interface Dossier {
  symbol: string; name: string; industry: string | null; built_at: string; latest_period: string; latest_label: string;
  documents: DocRef[];
  financials: {
    table: FinRow[]; latest: { current: Metrics; previous: Metrics | null; year_ago: Metrics | null;
      qoq: Record<string, number | null>; yoy: Record<string, number | null>; previous_period: string | null;
      year_ago_period: string | null; basis: string; financial: boolean; unit_note: string | null; checks: Check[];
      source: SourceRef };
    annual: (Metrics & { label: string; period_end: string })[]; annual_source: SourceRef | null;
    reconciliation: { quarter: string; metric: string; first: number; later: number; note: string }[];
    checks_failed: number;
  };
  promises: Promise_[]; dropped_claims: number; uncited_dropped: number;
  overview: Cited[]; bull: Cited[]; bear: Cited[]; narrative_gap: Cited | null;
  coverage: { results_quarters: string[]; transcript_quarters: string[] };
  usage: { calls: number; cached: number; tin: number; tout: number };
}
export interface ProgressItem { step: string; label: string; state: "pending" | "running" | "done" | "skipped"; detail: string | null }
export interface DossierStatus {
  symbol: string; status: "queued" | "running" | "ready" | "failed"; step: string | null;
  progress: ProgressItem[]; data: Dossier | null; error: string | null; built_at: string | null; started_at: string | null;
}

async function req2<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { ...init, headers: { "Content-Type": "application/json" } });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : msg; } catch { /* */ }
    const e = new Error(msg) as Error & { status?: number };
    e.status = r.status;
    throw e;
  }
  return r.json() as Promise<T>;
}

export const research = {
  list: () => req2<{ dossiers: { symbol: string; status: string; built_at: string | null; name: string | null; latest_label: string | null }[]; suggested: string[] }>("/api/research"),
  search: (q: string) => req2<{ results: { symbol: string; name: string }[]; source: string | null }>(`/api/search?q=${encodeURIComponent(q)}`),
  start: (symbol: string, force = false) => req2<DossierStatus>(`/api/research/${encodeURIComponent(symbol)}?force=${force}`, { method: "POST" }),
  get: (symbol: string) => req2<DossierStatus>(`/api/research/${encodeURIComponent(symbol)}`),
  page: (docId: string, page: number) => req2<{ id: string; title: string; url: string; page: number; text: string; pages: number }>(`/api/documents/${docId}/pages/${page}`),
};

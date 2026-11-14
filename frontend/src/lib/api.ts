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

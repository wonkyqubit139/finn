import type { DataMode, Tier } from "../lib/api";
import { absTime } from "../lib/format";

/** Priority as three stacked bars — readable at a glance, exact score on hover. */
export function SignalMark({ priority, tier }: { priority: number; tier: Tier }) {
  const filled = tier === "high" ? 3 : tier === "medium" ? 2 : 1;
  const fill = tier === "high" ? "var(--color-ink)" : tier === "medium" ? "var(--color-muted)" : "var(--color-faint)";
  return (
    <svg width="14" height="16" viewBox="0 0 14 16" role="img" aria-label={`Priority ${priority} of 100`}
         className="shrink-0">
      <title>{`Priority ${priority}/100`}</title>
      {[0, 1, 2].map((i) => (
        <rect key={i} x={i * 5} y={10 - i * 5} width="3.5" height={6 + i * 5} rx="1"
              fill={i < filled ? fill : "var(--color-rule)"} />
      ))}
    </svg>
  );
}

export function Sparkline({ values, up }: { values: number[]; up: boolean | null }) {
  if (values.length < 2) return <div className="w-[76px] h-6" />;
  const w = 76, h = 24, pad = 2;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => [pad + (i / (values.length - 1)) * (w - pad * 2), pad + (1 - (v - lo) / span) * (h - pad * 2)]);
  const last = pts[pts.length - 1];
  const dot = up == null ? "var(--color-muted)" : up ? "var(--color-up)" : "var(--color-down)";
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" className="shrink-0">
      <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke="var(--color-faint)" strokeWidth="1.25" />
      <circle cx={last[0]} cy={last[1]} r="2.25" fill={dot} />
    </svg>
  );
}

export function Change({ value, className = "" }: { value: number | null | undefined; className?: string }) {
  if (value == null) return <span className={`text-faint ${className}`}>–</span>;
  const c = value > 0 ? "text-up" : value < 0 ? "text-down" : "text-muted";
  const s = value > 0 ? "+" : value < 0 ? "−" : "";
  return <span className={`${c} ${className}`}>{s}{Math.abs(value).toFixed(2)}%</span>;
}

/** Tells the investor where the numbers come from whenever it isn't live data. */
export function DataBanner({ data, onRefresh, busy }: { data: DataMode; onRefresh?: () => void; busy?: boolean }) {
  if (data.mode === "live") return null;
  const snapshot = data.mode === "snapshot";
  return (
    <div className="mx-4 md:mx-0 mb-4 rounded-lg bg-warn-wash text-warn px-3.5 py-3 text-[13.5px] leading-snug">
      {snapshot ? (
        <p><strong className="font-semibold">Cached snapshot.</strong> Live exchange data couldn't be reached from this
          server, so you're seeing filings and prices saved on {snapshotTime(data.detail)}.</p>
      ) : (
        <p><strong className="font-semibold">No data yet.</strong> FINN hasn't fetched filings or prices on this server.</p>
      )}
      {onRefresh && (
        <button onClick={onRefresh} disabled={busy}
                className="mt-2 font-semibold underline underline-offset-2 disabled:opacity-60">
          {busy ? "Fetching from NSE, BSE and Yahoo…" : "Fetch live data now"}
        </button>
      )}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="mx-4 md:mx-0 rounded-lg border border-rule bg-surface px-4 py-3 text-[14px]">
      <p className="text-down font-medium">Couldn't load this view: {message}</p>
      {onRetry && <button onClick={onRetry} className="mt-1 text-accent font-semibold">Try again</button>}
    </div>
  );
}

export function Skeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="mx-4 md:mx-0 space-y-3" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-14 rounded-lg bg-wash/70" />
      ))}
    </div>
  );
}

function snapshotTime(detail?: string): string {
  const iso = detail?.replace("captured ", "");
  return iso && !Number.isNaN(Date.parse(iso)) ? absTime(iso) : "an earlier date";
}

import { useEffect, useState } from "react";
import { api, type Settings } from "../lib/api";
import { CATEGORY_LABEL, relTime } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { ErrorNote, Skeleton } from "../components/bits";

const SOURCE_LABEL: Record<string, string> = {
  nse: "NSE announcements", bse: "BSE announcements (fallback)", yahoo: "Yahoo Finance prices",
  llm: "Language model", snapshot: "Cached snapshot",
};

export function SettingsScreen({ onDataChanged }: { onDataChanged: () => void }) {
  const s = useAsync(() => api.settings(), []);
  const src = useAsync(() => api.sources(), []);
  const usage = useAsync(() => api.usage(), []);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  useEffect(() => { if (s.data) setDraft(s.data.settings); }, [s.data]);

  async function save() {
    if (!draft) return;
    setSaveErr(null);
    try {
      const { last_seen_at: _ignored, ...rest } = draft;
      void _ignored;
      await api.saveSettings(rest);
      setSaved("Alert rules saved. Feed priorities updated.");
      onDataChanged();
    } catch (e) { setSaveErr((e as Error).message); }
  }

  async function refresh() {
    setRefreshing(true);
    setRefreshNote(null);
    try {
      const r = await api.refresh() as { status: string; seconds?: number; alerts_raised?: number };
      setRefreshNote(r.status === "already_running" ? "A refresh is already running." :
        `Refreshed in ${r.seconds}s. ${r.alerts_raised ?? 0} new alert${r.alerts_raised === 1 ? "" : "s"}.`);
    } catch (e) { setRefreshNote(`Refresh failed: ${(e as Error).message}`); }
    setRefreshing(false);
    src.reload(); usage.reload(); onDataChanged();
  }

  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => { setDraft((d) => d && { ...d, [k]: v }); setSaved(null); };

  return (
    <div className="px-4 md:px-0">
      <h1 className="text-[26px] md:text-[30px] font-[750] tracking-[-0.025em] leading-tight">Alerts & data</h1>
      <p className="mt-1 text-muted text-[14px]">You decide what counts as unusual. FINN checks after every refresh.</p>

      {s.loading && !draft && <div className="mt-6"><Skeleton rows={4} /></div>}
      {s.error && <div className="mt-6"><ErrorNote message={s.error} onRetry={s.reload} /></div>}

      {draft && s.data && (
        <section className="mt-6 bg-surface rounded-lg border border-rule p-4 md:p-5">
          <h2 className="text-[16px] font-semibold">Market alerts</h2>
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-4">
            <NumField label="Price move beyond ±" unit="%" step={0.5} min={0.5} max={50}
                      value={draft.price_move_pct} onChange={(v) => set("price_move_pct", v)} />
            <NumField label="Volume above" unit="× average" step={0.1} min={1.1} max={20}
                      value={draft.volume_multiple} onChange={(v) => set("volume_multiple", v)} />
            <NumField label="Average over the last" unit="sessions" step={1} min={5} max={120}
                      value={draft.volume_lookback_days} onChange={(v) => set("volume_lookback_days", Math.round(v))} />
          </div>

          <h2 className="mt-7 text-[16px] font-semibold">Filings that should alert you</h2>
          <p className="text-[13.5px] text-muted">Watched types also rank slightly higher in the feed.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {s.data.categories.filter((c) => c !== "unclassified").map((c) => {
              const on = draft.watched_categories.includes(c);
              return (
                <button key={c} aria-pressed={on}
                        onClick={() => set("watched_categories", on ? draft.watched_categories.filter((x) => x !== c) : [...draft.watched_categories, c])}
                        className={`h-8 px-3 rounded-full text-[13.5px] border ${on ? "bg-accent-wash border-accent text-accent font-semibold" : "bg-surface border-rule text-muted"}`}>
                  {CATEGORY_LABEL[c] ?? c}
                </button>
              );
            })}
          </div>
          <div className="mt-4 max-w-xs">
            <NumField label="Only if priority is at least" unit="/ 100" step={5} min={0} max={100}
                      value={draft.announcement_alert_min_priority} onChange={(v) => set("announcement_alert_min_priority", Math.round(v))} />
          </div>

          <div className="mt-6 flex items-center gap-3">
            <button onClick={save} className="h-10 px-4 rounded-lg bg-accent text-white font-semibold text-[14.5px]">Save alert rules</button>
            {saved && <span className="text-[13.5px] text-up">{saved}</span>}
            {saveErr && <span className="text-[13.5px] text-down">Not saved: {saveErr}</span>}
          </div>
        </section>
      )}

      <section className="mt-6 bg-surface rounded-lg border border-rule p-4 md:p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-[16px] font-semibold">Data sources</h2>
          <button onClick={refresh} disabled={refreshing}
                  className="h-9 px-3.5 rounded-lg border border-ink text-ink font-semibold text-[14px] disabled:opacity-60">
            {refreshing ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
        {refreshNote && <p className="mt-2 text-[13.5px] text-muted">{refreshNote}</p>}
        {src.data && (
          <>
            <ul className="mt-3 divide-y divide-rule text-[14px]">
              {src.data.sources.length === 0 && <li className="py-2 text-muted">Nothing fetched yet.</li>}
              {src.data.sources.map((r) => {
                const okNewer = r.last_ok && (!r.last_error_at || r.last_ok >= r.last_error_at);
                return (
                  <li key={r.source} className="py-2.5">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="font-medium">{SOURCE_LABEL[r.source] ?? r.source}</span>
                      <span className={`text-[13px] font-semibold ${okNewer ? "text-up" : "text-down"}`}>
                        {okNewer ? `OK ${relTime(r.last_ok!)}` : r.last_error_at ? `Failed ${relTime(r.last_error_at)}` : "Not used"}
                      </span>
                    </div>
                    {!okNewer && r.last_error && <p className="text-[12.5px] text-muted break-words">{r.last_error}</p>}
                    {okNewer && r.detail && <p className="text-[12.5px] text-faint">{r.detail}</p>}
                  </li>
                );
              })}
            </ul>
            <p className="mt-2 text-[12.5px] text-faint">
              {src.data.counts.announcements} filings and {src.data.counts.price_rows} daily price rows stored.
            </p>
          </>
        )}
      </section>

      {usage.data && (
        <section className="mt-6 mb-4 bg-surface rounded-lg border border-rule p-4 md:p-5">
          <h2 className="text-[16px] font-semibold">Model usage</h2>
          {!usage.data.fast_model ? (
            <p className="mt-1 text-[13.5px] text-muted">No model key configured. Filings are classified by rules only.</p>
          ) : usage.data.by_task.length === 0 ? (
            <p className="mt-1 text-[13.5px] text-muted">Model: {usage.data.fast_model}. No calls yet.</p>
          ) : (
            <table className="mt-2 w-full text-[13.5px]">
              <thead className="text-muted text-left">
                <tr><th className="font-medium py-1">Task</th><th className="font-medium">Calls</th><th className="font-medium">From cache</th><th className="font-medium text-right">Tokens in / out</th></tr>
              </thead>
              <tbody>
                {usage.data.by_task.map((t) => (
                  <tr key={t.task + t.model} className="border-t border-rule">
                    <td className="py-1.5">{t.task}<div className="text-[12px] text-faint">{t.model}</div></td>
                    <td>{t.calls}</td><td>{t.cache_hits}</td>
                    <td className="text-right">{t.prompt_tokens.toLocaleString("en-IN")} / {t.completion_tokens.toLocaleString("en-IN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  );
}

function NumField({ label, unit, value, onChange, step, min, max }: {
  label: string; unit: string; value: number; onChange: (v: number) => void; step: number; min: number; max: number;
}) {
  return (
    <label className="block">
      <span className="block text-[13px] text-muted mb-1">{label}</span>
      <span className="flex items-center gap-2">
        <input type="number" inputMode="decimal" value={value} step={step} min={min} max={max}
               onChange={(e) => onChange(Number(e.target.value))}
               className="w-24 h-10 px-3 rounded-lg border border-rule bg-ground/50 text-[15px] font-medium" />
        <span className="text-[13.5px] text-muted">{unit}</span>
      </span>
    </label>
  );
}

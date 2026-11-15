import { useState } from "react";
import { api, type Announcement, type MarketAlert } from "../lib/api";
import { absDate, absTime, categoryLabel, relTime } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { DataBanner, ErrorNote, SignalMark, Skeleton } from "../components/bits";
import { ChecksLine, ResultsTable } from "../components/ResultsTable";
import type { PeopleEnrichment, ResultsEnrichment } from "../lib/api";

const WINDOWS: { key: string; label: string }[] = [
  { key: "since_last", label: "Since last visit" },
  { key: "24h", label: "24 hours" },
  { key: "3d", label: "3 days" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
];

export function FeedScreen({ onDataChanged, openResearch }: { onDataChanged: () => void; openResearch: (s: string) => void }) {
  const [win, setWin] = useState("24h");
  const [busy, setBusy] = useState(false);
  const { data, error, loading, reload } = useAsync(() => api.feed(win), [win]);

  async function fetchLive() {
    setBusy(true);
    try { await api.refresh(); } finally { setBusy(false); reload(); onDataChanged(); }
  }

  const g = data?.groups;
  const nHigh = g?.high.length ?? 0, nMed = g?.medium.length ?? 0, nRoutine = g?.routine.length ?? 0;

  return (
    <div>
      <div className="px-4 md:px-0">
        <h1 className="text-[26px] md:text-[30px] font-[750] tracking-[-0.025em] leading-tight">What changed</h1>
        {data && (
          <p className="mt-1 text-muted text-[14px]">
            {data.total === 0 ? "No filings across your holdings in this window."
              : `${nHigh} need attention, ${nMed} worth a look, ${nRoutine} routine.`}
          </p>
        )}
      </div>

      <div className="mt-4 mb-5 flex gap-2 overflow-x-auto px-4 md:px-0 no-scrollbar" role="tablist" aria-label="Time window">
        {WINDOWS.map((w) => (
          <button key={w.key} role="tab" aria-selected={win === w.key} onClick={() => setWin(w.key)}
                  className={`shrink-0 h-8 px-3 rounded-full text-[13.5px] border ${win === w.key
                    ? "bg-ink text-white border-ink font-semibold" : "bg-surface border-rule text-ink hover:border-faint"}`}>
            {w.label}
          </button>
        ))}
      </div>

      {data && <DataBanner data={data.data} onRefresh={fetchLive} busy={busy} />}
      {loading && !data && <Skeleton />}
      {error && <ErrorNote message={error} onRetry={reload} />}

      {data && (
        <div className={loading ? "opacity-60 transition-opacity" : ""}>
          {data.market_alerts.length > 0 && <MarketMoves alerts={data.market_alerts} />}

          {nHigh > 0 && <Group title="Needs your attention" items={g!.high} openResearch={openResearch} />}
          {nMed > 0 && <Group title="Worth a look" items={g!.medium} openResearch={openResearch} />}
          {nHigh + nMed === 0 && data.total > 0 && (
            <p className="px-4 md:px-0 mb-6 text-[14.5px]">Nothing material in this window, only routine paperwork.</p>
          )}
          {data.total === 0 && data.data.mode !== "empty" && (
            <div className="px-4 md:px-0 mb-6 text-[14.5px]">
              <p>Quiet across all holdings.</p>
              {win !== "7d" && <button onClick={() => setWin("7d")} className="mt-1 text-accent font-semibold">See the last 7 days</button>}
            </div>
          )}
          {nRoutine > 0 && <Routine items={g!.routine} />}
        </div>
      )}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="px-4 md:px-0 mb-2 text-[13px] font-semibold text-muted">{children}</h2>;
}

function MarketMoves({ alerts }: { alerts: MarketAlert[] }) {
  // One row per stock and session: price move and volume spike side by side.
  const rows = new Map<string, { symbol: string; ref: string; price?: number; volume?: number }>();
  for (const a of alerts) {
    const k = `${a.symbol}:${a.ref}`;
    const r = rows.get(k) ?? { symbol: a.symbol, ref: a.ref };
    if (a.kind === "price") r.price = a.value; else r.volume = a.value;
    rows.set(k, r);
  }
  const dates = [...new Set(alerts.map((a) => a.ref))];
  return (
    <section className="mb-7">
      <SectionTitle>Unusual moves{dates.length === 1 ? `, ${absDate(dates[0])} close` : ""}</SectionTitle>
      <ul className="bg-surface md:rounded-lg border-y md:border border-rule divide-y divide-rule">
        {[...rows.values()].map((r) => (
          <li key={r.symbol + r.ref} className="flex items-baseline gap-3 px-4 py-2.5">
            <span className="flex-1 min-w-0 font-semibold text-[14px]">
              {r.symbol}
              {dates.length > 1 && <span className="font-normal text-faint text-[13px]"> {absDate(r.ref)}</span>}
            </span>
            <span className="w-[84px] text-right text-[14px] text-muted">
              {r.volume != null ? <><span className="font-semibold text-ink">{r.volume.toFixed(1)}×</span> vol</> : ""}
            </span>
            <span className={`w-[64px] text-right font-semibold text-[14.5px] ${r.price == null ? "text-faint"
              : r.price > 0 ? "text-up" : "text-down"}`}>
              {r.price == null ? "" : `${r.price > 0 ? "+" : "−"}${Math.abs(r.price).toFixed(1)}%`}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Group({ title, items, openResearch }: { title: string; items: Announcement[]; openResearch: (s: string) => void }) {
  return (
    <section className="mb-7">
      <SectionTitle>{title}</SectionTitle>
      <ul className="bg-surface md:rounded-lg border-y md:border border-rule divide-y divide-rule">
        {items.map((a) => <FilingRow key={a.id} a={a} openResearch={openResearch} />)}
      </ul>
    </section>
  );
}

function FilingRow({ a, openResearch }: { a: Announcement; openResearch: (s: string) => void }) {
  const [open, setOpen] = useState(false);
  const by = a.classified_by?.startsWith("llm:") ? `model (${a.classified_by.slice(4)})`
    : a.classified_by === "default" ? "default (no rule matched)" : "exchange subject rule";
  return (
    <li>
      <button onClick={() => setOpen(!open)} aria-expanded={open}
              className="w-full text-left px-4 py-3.5 flex gap-3 hover:bg-ground/60">
        <span className="pt-1"><SignalMark priority={a.priority} tier={a.tier} /></span>
        <span className="flex-1 min-w-0">
          <span className="flex items-baseline gap-2">
            <span className="font-semibold text-[14.5px]">{a.symbol}</span>
            <span className="text-[13px] text-muted min-w-0 truncate">{categoryLabel(a.category, a.sub_type)}</span>
            <span className="ml-auto shrink-0 text-[12.5px] text-faint" title={absTime(a.published_at)}>{relTime(a.published_at)}</span>
          </span>
          <span className="block mt-1 text-[14.5px] leading-snug text-ink">{a.headline}</span>
        </span>
      </button>
      {a.enrichment?.ok && a.enrichment.type === "results" && <ResultsCard e={a.enrichment} />}
      {a.enrichment?.ok && a.enrichment.type === "people" && <PeopleCard e={a.enrichment} />}
      {open && (
        <div className="px-4 pb-4 pl-[46px] text-[13.5px] text-muted space-y-1.5">
          <p><span className="text-ink">{a.company}</span>. Filed {absTime(a.published_at)} on {a.source.toUpperCase()} as “{a.subject}”.</p>
          <p>Priority {a.priority}/100, set by {by}.</p>
          <div className="flex gap-4 pt-1">
            {a.attachment_url && (
              <a href={a.attachment_url} target="_blank" rel="noreferrer"
                 className="font-semibold text-accent underline underline-offset-2">Open the filing (PDF)</a>
            )}
            <button onClick={() => openResearch(a.symbol)} className="font-semibold text-accent underline underline-offset-2">
              Research {a.symbol}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

function Routine({ items }: { items: Announcement[] }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="mb-8">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
              className="mx-4 md:mx-0 text-[14px] font-semibold text-accent">
        {open ? "Hide" : "Show"} {items.length} routine filing{items.length === 1 ? "" : "s"}
      </button>
      {open && (
        <ul className="mt-3 bg-surface md:rounded-lg border-y md:border border-rule divide-y divide-rule">
          {items.map((a) => (
            <li key={a.id} className="px-4 py-2.5 flex items-baseline gap-3 text-[13.5px]">
              <span className="w-24 shrink-0 font-medium">{a.symbol}</span>
              <span className="flex-1 min-w-0 text-muted truncate">{a.subject}</span>
              {a.attachment_url
                ? <a href={a.attachment_url} target="_blank" rel="noreferrer" className="shrink-0 text-accent">PDF</a>
                : null}
              <span className="shrink-0 text-faint w-14 text-right">{relTime(a.published_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ResultsCard({ e }: { e: ResultsEnrichment }) {
  return (
    <div className="mx-4 mb-3.5 ml-[46px] rounded-lg bg-ground/70 px-3 py-2">
      <div className="text-[12.5px] text-muted mb-1">{e.period_label}, {e.basis} figures read from the filing</div>
      <ResultsTable current={e.current} qoq={e.qoq} yoy={e.yoy} financial={e.financial} compact />
      <p className="mt-1.5 text-[12px] text-muted leading-snug">
        <ChecksLine checks={e.checks} />{" "}
        <a href={e.url} target="_blank" rel="noreferrer" className="text-accent font-semibold">Statement on page {e.page}</a>
      </p>
    </div>
  );
}

function PeopleCard({ e }: { e: PeopleEnrichment }) {
  return (
    <div className="mx-4 mb-3.5 ml-[46px] rounded-lg bg-ground/70 px-3 py-2 space-y-1.5 text-[13.5px]">
      {e.changes.map((c, i) => (
        <p key={i} className="leading-snug">
          <strong className="font-semibold">{c.person}</strong>, {c.role} ({c.change}{c.effective ? `, effective ${c.effective}` : ""}).
          {c.background && <span className="text-muted"> {c.background}</span>}
          {c.page && <a href={e.url} target="_blank" rel="noreferrer" className="ml-1 text-[12px] text-accent font-semibold">p{c.page}</a>}
        </p>
      ))}
    </div>
  );
}

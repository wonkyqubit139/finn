import { useEffect, useRef, useState } from "react";
import { research } from "../lib/api";
import { relTime } from "../lib/format";
import { useAsync } from "../lib/useAsync";

export function ResearchScreen({ open }: { open: (symbol: string) => void }) {
  const list = useAsync(() => research.list(), []);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ symbol: string; name: string }[]>([]);
  const t = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(t.current);
    if (q.trim().length < 2) { setHits([]); return; }
    t.current = window.setTimeout(() => {
      research.search(q).then((r) => setHits(r.results)).catch(() => setHits([]));
    }, 250);
  }, [q]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const s = (hits[0]?.symbol && hits[0].symbol.toUpperCase() === q.trim().toUpperCase()) ? hits[0].symbol : q.trim().toUpperCase();
    if (s) open(s);
  }

  return (
    <div className="px-4 md:px-0">
      <h1 className="text-[26px] md:text-[30px] font-[750] tracking-[-0.025em] leading-tight">Research</h1>
      <p className="mt-1 text-muted text-[14px] max-w-[60ch]">
        Any NSE-listed company. Built only from its own filings: results statements and concall transcripts.
        Every figure and claim links to the page it came from.
      </p>

      <form onSubmit={submit} className="mt-5 relative" role="search">
        <label htmlFor="sym" className="sr-only">Company or NSE symbol</label>
        <input id="sym" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" autoCapitalize="characters"
               placeholder="Company or NSE symbol"
               className="w-full h-12 pl-4 pr-28 rounded-lg border border-rule bg-surface text-[15.5px] placeholder:text-faint" />
        <button type="submit" className="absolute right-1.5 top-1.5 h-9 px-4 rounded-md bg-accent text-white font-semibold text-[14px]">
          Research
        </button>
        {hits.length > 0 && (
          <ul className="absolute z-10 mt-1 w-full bg-surface border border-rule rounded-lg shadow-[0_6px_24px_rgba(24,32,44,0.08)] overflow-hidden">
            {hits.map((h) => (
              <li key={h.symbol}>
                <button type="button" onClick={() => open(h.symbol)} className="w-full text-left px-4 py-2.5 hover:bg-ground flex gap-3 items-baseline">
                  <span className="font-semibold text-[14.5px] w-28 shrink-0">{h.symbol}</span>
                  <span className="text-[13.5px] text-muted truncate">{h.name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </form>

      {list.data && list.data.suggested.length > 0 && (
        <div className="mt-5 flex flex-wrap items-center gap-2 text-[13.5px]">
          <span className="text-muted mr-1">Try</span>
          {list.data.suggested.map((s) => (
            <button key={s} onClick={() => open(s)} className="h-8 px-3 rounded-full border border-rule bg-surface font-medium hover:border-faint">{s}</button>
          ))}
        </div>
      )}

      {list.data && list.data.dossiers.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-2 text-[13px] font-semibold text-muted">Your research</h2>
          <ul className="bg-surface rounded-lg border border-rule divide-y divide-rule">
            {list.data.dossiers.map((d) => (
              <li key={d.symbol}>
                <button onClick={() => open(d.symbol)} className="w-full text-left px-4 py-3 flex items-baseline gap-3 hover:bg-ground/60">
                  <span className="font-semibold text-[14.5px] w-28 shrink-0">{d.symbol}</span>
                  <span className="flex-1 min-w-0 text-[13.5px] text-muted truncate">{d.name ?? ""}{d.latest_label ? `, latest ${d.latest_label}` : ""}</span>
                  <span className="text-[12.5px] text-faint shrink-0">
                    {d.status === "ready" && d.built_at ? relTime(d.built_at) : d.status === "failed" ? "failed" : "building…"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

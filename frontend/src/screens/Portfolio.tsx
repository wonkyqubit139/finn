import { useMemo, useState } from "react";
import { api, type Holding } from "../lib/api";
import { absDate, compactVol, inr } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { Change, DataBanner, ErrorNote, Skeleton, Sparkline } from "../components/bits";

type Sort = "move" | "activity" | "name";

export function PortfolioScreen({ openResearch }: { openResearch: (s: string) => void }) {
  const { data, error, loading, reload } = useAsync(() => api.portfolio(), []);
  const [sort, setSort] = useState<Sort>("move");

  const rows = useMemo(() => {
    const h = [...(data?.holdings ?? [])];
    if (sort === "move") h.sort((a, b) => Math.abs(b.eod?.change_pct ?? 0) - Math.abs(a.eod?.change_pct ?? 0));
    if (sort === "activity") h.sort((a, b) => b.notable_7d - a.notable_7d || (b.top_filing?.priority ?? 0) - (a.top_filing?.priority ?? 0));
    if (sort === "name") h.sort((a, b) => a.symbol.localeCompare(b.symbol));
    return h;
  }, [data, sort]);

  const asOf = data?.holdings.find((h) => h.eod)?.eod?.date;

  return (
    <div>
      <div className="px-4 md:px-0">
        <h1 className="text-[26px] md:text-[30px] font-[750] tracking-[-0.025em] leading-tight">Portfolio</h1>
        <p className="mt-1 text-muted text-[14px]">
          {data ? `${data.holdings.length} holdings` : "Loading"}{asOf ? `. End-of-day prices for ${absDate(asOf)}.` : "."}
        </p>
      </div>

      <div className="mt-4 mb-4 px-4 md:px-0 flex items-center gap-2 text-[13.5px]" role="group" aria-label="Sort">
        <span className="text-muted mr-1">Sort by</span>
        {([["move", "Day's move"], ["activity", "Filings"], ["name", "Name"]] as [Sort, string][]).map(([k, l]) => (
          <button key={k} onClick={() => setSort(k)} aria-pressed={sort === k}
                  className={`h-7 px-2.5 rounded-full border ${sort === k ? "bg-ink text-white border-ink font-semibold" : "bg-surface border-rule"}`}>
            {l}
          </button>
        ))}
      </div>

      {data && <DataBanner data={data.data} />}
      {loading && !data && <Skeleton rows={8} />}
      {error && <ErrorNote message={error} onRetry={reload} />}

      {data && (
        <ul className="bg-surface md:rounded-lg border-y md:border border-rule divide-y divide-rule">
          {rows.map((h) => <HoldingRow key={h.symbol} h={h} pctT={data.thresholds.price_move_pct} volT={data.thresholds.volume_multiple} open={() => openResearch(h.symbol)} />)}
        </ul>
      )}
      {data && (
        <p className="px-4 md:px-0 mt-3 text-[12.5px] text-faint">
          Prices: Yahoo Finance end-of-day{data.holdings.some((h) => h.price_source === "snapshot") ? " (cached snapshot)" : ""}.
          Volume compared with the trailing average of previous sessions. Tap a holding to research it.
        </p>
      )}
    </div>
  );
}

function HoldingRow({ h, pctT, volT, open }: { h: Holding; pctT: number; volT: number; open: () => void }) {
  const e = h.eod;
  const bigMove = e?.change_pct != null && Math.abs(e.change_pct) >= pctT;
  const bigVol = e?.volume_multiple != null && e.volume_multiple >= volT;
  return (
    <li className="px-4 py-3 cursor-pointer hover:bg-ground/60" onClick={open}
        onKeyDown={(e) => { if (e.key === "Enter") open(); }} tabIndex={0} aria-label={`Research ${h.symbol}`}>
      <div className="flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-[15px]">{h.symbol}</div>
          <div className="text-[12.5px] text-muted truncate">{h.name}<span className="text-faint">, {h.sector}</span></div>
        </div>
        <Sparkline values={h.spark} up={e?.change_pct == null ? null : e.change_pct >= 0} />
        <div className="w-[92px] text-right">
          <div className="text-[14.5px] font-medium">{e ? inr(e.close) : "–"}</div>
          <Change value={e?.change_pct} className={`text-[13px] ${bigMove ? "font-bold" : ""}`} />
        </div>
      </div>
      {(bigVol || h.top_filing) && (
        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[13px]">
          {bigVol && (
            <span className="font-semibold text-ink">
              Volume {e!.volume_multiple!.toFixed(1)}× average ({compactVol(e!.volume)})
            </span>
          )}
          {h.top_filing && (
            <span className="text-muted min-w-0 truncate">
              {h.notable_7d > 1 ? `${h.notable_7d} notable filings this week. Top: ` : "This week: "}
              <span className="text-ink">{h.top_filing.headline}</span>
            </span>
          )}
        </div>
      )}
    </li>
  );
}

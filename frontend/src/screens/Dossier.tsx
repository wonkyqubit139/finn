import { useCallback, useEffect, useRef, useState } from "react";
import { research, type Dossier, type DossierStatus, type Promise_ } from "../lib/api";
import { crore, relTime } from "../lib/format";
import { CitationProvider, Cite, kindLabel } from "../components/Citations";
import { ChecksLine, ResultsTable } from "../components/ResultsTable";

export function DossierScreen({ symbol, back }: { symbol: string; back: () => void }) {
  const [st, setSt] = useState<DossierStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const poll = useCallback(async () => {
    try {
      const s = await research.get(symbol);
      setSt(s);
      if (s.status === "queued" || s.status === "running") timer.current = window.setTimeout(poll, 2000);
    } catch (e) { setErr((e as Error).message); }
  }, [symbol]);

  const start = useCallback(async (force = false) => {
    setErr(null);
    try {
      const s = await research.start(symbol, force);
      setSt(s);
      if (s.status === "queued" || s.status === "running") timer.current = window.setTimeout(poll, 1500);
    } catch (e) { setErr((e as Error).message); }
  }, [symbol, poll]);

  useEffect(() => {
    start(false);
    return () => window.clearTimeout(timer.current);
  }, [start]);

  const building = st && (st.status === "queued" || st.status === "running");
  const d = st?.data;

  return (
    <div className="px-4 md:px-0">
      <button onClick={back} className="text-[14px] text-accent font-semibold mb-3">Research</button>
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-[26px] md:text-[30px] font-[750] tracking-[-0.025em] leading-tight min-w-0">
          {d?.name ?? symbol}
        </h1>
        {d && !building && (
          <button onClick={() => start(true)} className="shrink-0 text-[13.5px] font-semibold text-accent">Rebuild</button>
        )}
      </div>
      <p className="mt-1 text-[14px] text-muted">
        {symbol}{d?.industry ? `, ${d.industry}` : ""}
        {d ? `. Latest results ${d.latest_label}. Built ${relTime(d.built_at)} from ${d.documents.length} filings.` : ""}
      </p>

      {err && <p className="mt-4 text-down text-[14px]">{err}</p>}
      {(building || (st?.status === "failed")) && <BuildProgress st={st!} retry={() => start(true)} />}
      {d && <DossierBody d={d} />}
    </div>
  );
}

function BuildProgress({ st, retry }: { st: DossierStatus; retry: () => void }) {
  return (
    <section className="mt-5 bg-surface rounded-lg border border-rule p-4" aria-live="polite">
      <h2 className="text-[15px] font-semibold">
        {st.status === "failed" ? "Couldn't build this research" : st.data ? "Updating with the latest filings" : "Reading the company's filings"}
      </h2>
      {st.status !== "failed" && <p className="text-[13px] text-muted">First build takes 1–3 minutes. Later views load instantly from cache.</p>}
      <ol className="mt-3 space-y-2">
        {st.progress.map((p) => (
          <li key={p.step} className="flex gap-3 text-[14px]">
            <span className="w-4 shrink-0 text-center" aria-hidden="true">
              {p.state === "done" ? <span className="text-up">✓</span> : p.state === "running" ? <span className="inline-block w-2 h-2 rounded-full bg-accent animate-pulse" /> : p.state === "skipped" ? "–" : <span className="text-faint">·</span>}
            </span>
            <span className={p.state === "pending" ? "text-faint" : ""}>
              {p.label}{p.detail && <span className="text-muted">: {p.detail}</span>}
            </span>
          </li>
        ))}
      </ol>
      {st.status === "failed" && (
        <>
          <p className="mt-3 text-[14px] text-down">{st.error}</p>
          <button onClick={retry} className="mt-2 text-accent font-semibold text-[14px]">Try again</button>
        </>
      )}
    </section>
  );
}

const STATUS: Record<Promise_["status"], { label: string; cls: string }> = {
  delivered: { label: "Delivered", cls: "bg-[#E2F2E9] text-up" },
  on_track: { label: "On track", cls: "bg-[#E2F2E9] text-up" },
  missed: { label: "Missed", cls: "bg-[#F8E3E1] text-down" },
  off_track: { label: "Off track", cls: "bg-[#F8E3E1] text-down" },
  pending: { label: "Not yet due", cls: "bg-wash text-muted" },
  unverifiable: { label: "Can't verify from statements", cls: "bg-wash text-muted" },
};
const ORDER: Promise_["status"][] = ["missed", "off_track", "delivered", "on_track", "pending", "unverifiable"];

function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="text-[18px] font-[700] tracking-[-0.01em]">{title}</h2>
      {sub && <p className="text-[13px] text-muted mt-0.5 max-w-[65ch]">{sub}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function DossierBody({ d }: { d: Dossier }) {
  const f = d.financials;
  const L = f.latest;
  const scored = d.promises.filter((p) => ["delivered", "missed", "on_track", "off_track"].includes(p.status));
  return (
    <CitationProvider docs={d.documents}>
      {/* Latest quarter */}
      <Section title={`${d.latest_label} results`} sub={`${L.basis === "standalone" ? "Standalone" : "Consolidated"} figures from the company's results filing. QoQ vs ${L.previous_period ? "the previous quarter" : "–"}, YoY vs the same quarter last year.`}>
        <div className="bg-surface rounded-lg border border-rule px-4 py-3">
          <ResultsTable current={L.current} qoq={L.qoq} yoy={L.yoy} financial={L.financial} />
          <p className="mt-2 text-[12.5px] text-muted leading-snug">
            {L.financial ? "EBITDA isn't meaningful for lenders. " : L.current.ebitda != null ? `EBITDA = ${L.current.ebitda_note}. ` : `EBITDA not shown: ${L.current.ebitda_note} `}
            <ChecksLine checks={L.checks} />
            {L.unit_note && <> {L.unit_note}</>}
            <Cite refName={L.source.ref} page={L.source.page} />
          </p>
        </div>
      </Section>

      {/* Promise tracker */}
      <Section title="Promise tracker"
               sub="What management guided on recent earnings calls, checked against the numbers they later reported. Quotes are verified word-for-word against the transcript.">
        {d.narrative_gap?.text && (
          <p className="mb-4 text-[14.5px] leading-relaxed max-w-[68ch]">
            {d.narrative_gap.text}{d.narrative_gap.cite.map((c) => <Cite key={c} tag={c} />)}
          </p>
        )}
        <PromiseSummary promises={d.promises} />
        {d.promises.length === 0 ? (
          <p className="text-[14px] text-muted">No forward-looking statements found in the transcripts available.</p>
        ) : (
          <ul className="bg-surface rounded-lg border border-rule divide-y divide-rule">
            {[...d.promises].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || b.said_in.localeCompare(a.said_in))
              .map((p) => <PromiseRow key={p.id} p={p} />)}
          </ul>
        )}
        <p className="mt-2 text-[12.5px] text-faint">
          {scored.length} of {d.promises.length} statements scored in code against reported figures.
          {d.dropped_claims > 0 && ` ${d.dropped_claims} withheld because their quote couldn't be found in the transcript.`}
        </p>
      </Section>

      {/* Trend */}
      <Section title="Quarterly trend" sub="₹ crore. Each quarter as reported in its own results filing.">
        <div className="bg-surface rounded-lg border border-rule overflow-x-auto">
          <table className="w-full text-[13.5px] min-w-[520px]">
            <thead className="text-muted text-[12px]">
              <tr>
                <th className="text-left font-medium px-4 py-2">Quarter</th>
                <th className="text-right font-medium px-2">{L.financial ? "Income" : "Revenue"}</th>
                <th className="text-right font-medium px-2">YoY</th>
                <th className="text-right font-medium px-2">EBITDA %</th>
                <th className="text-right font-medium px-2">PAT</th>
                <th className="text-right font-medium px-2">YoY</th>
                <th className="text-right font-medium px-4">Source</th>
              </tr>
            </thead>
            <tbody>
              {f.table.map((r) => (
                <tr key={r.period_end} className="border-t border-rule">
                  <td className="px-4 py-2 font-medium">{r.label}</td>
                  <td className="text-right px-2">{crore(r.revenue)}</td>
                  <td className="text-right px-2"><Pct v={r.revenue_yoy} /></td>
                  <td className="text-right px-2">{r.ebitda_margin == null ? <span className="text-faint">–</span> : `${r.ebitda_margin.toFixed(1)}%`}</td>
                  <td className="text-right px-2">{crore(r.pat)}</td>
                  <td className="text-right px-2"><Pct v={r.pat_yoy} /></td>
                  <td className="text-right px-4"><Cite refName={r.source.ref} page={r.source.page} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {f.annual.length > 0 && (
          <p className="mt-2 text-[13.5px]">
            {f.annual.map((a, i) => (
              <span key={a.label}>{i > 0 ? "; " : ""}<strong className="font-semibold">{a.label}</strong> revenue ₹{crore(a.revenue)} cr, PAT ₹{crore(a.pat)} cr{a.ebitda_margin != null ? `, EBITDA margin ${a.ebitda_margin.toFixed(1)}%` : ""}</span>
            ))}.
            {f.annual_source && <Cite refName={f.annual_source.ref} page={f.annual_source.page} />}
          </p>
        )}
        {f.reconciliation.length > 0 && (
          <p className="mt-2 text-[13px] text-warn">
            Figures differ between filings for {f.reconciliation.map((r) => `${r.quarter} ${r.metric} (${r.first} vs ${r.later})`).join(", ")}: likely a restatement; check the notes.
          </p>
        )}
      </Section>

      {/* Synthesis */}
      {(d.overview.length > 0 || d.bull.length > 0) && (
        <Section title="The business, and the case for and against" sub="Written by the model from the material above only. Points it couldn't cite were removed.">
          {d.overview.length > 0 && (
            <p className="mb-4 text-[14.5px] leading-relaxed max-w-[68ch]">
              {d.overview.map((o, i) => <span key={i}>{o.text}{o.cite.map((c) => <Cite key={c} tag={c} />)} </span>)}
            </p>
          )}
          <div className="grid md:grid-cols-2 gap-3">
            <CaseList title="Bull case" items={d.bull} />
            <CaseList title="Bear case" items={d.bear} />
          </div>
        </Section>
      )}

      {/* Sources */}
      <Section title="Sources" sub="Primary documents only, fetched from the company's NSE filings.">
        <ul className="bg-surface rounded-lg border border-rule divide-y divide-rule text-[13.5px]">
          {d.documents.map((doc) => (
            <li key={doc.ref} className="px-4 py-2.5 flex gap-3 items-baseline">
              <span className="font-semibold w-8 shrink-0">{doc.ref}</span>
              <span className="flex-1 min-w-0">
                {kindLabel(doc.kind)}{doc.period_label ? `, ${doc.period_label}` : ""}
                <span className="text-faint">{doc.pages ? `, ${doc.pages} pages` : ""}</span>
              </span>
              <a href={doc.url} target="_blank" rel="noreferrer" className="text-accent font-semibold shrink-0">PDF</a>
            </li>
          ))}
        </ul>
        <p className="mt-2 mb-6 text-[12.5px] text-faint">
          Model calls for this build: {d.usage.calls} ({d.usage.cached} from cache), {d.usage.tin.toLocaleString("en-IN")} tokens in, {d.usage.tout.toLocaleString("en-IN")} out.
          Coverage: results for {d.coverage.results_quarters.join(", ") || "none"}; transcripts for {d.coverage.transcript_quarters.join(", ") || "none"}.
        </p>
      </Section>
    </CitationProvider>
  );
}

function Pct({ v }: { v: number | null }) {
  if (v == null) return <span className="text-faint">–</span>;
  return <span className={v >= 0 ? "text-up" : "text-down"}>{v >= 0 ? "+" : "−"}{Math.abs(v).toFixed(1)}%</span>;
}

function PromiseSummary({ promises }: { promises: Promise_[] }) {
  const c = (s: Promise_["status"][]) => promises.filter((p) => s.includes(p.status)).length;
  const items: [string, number, string][] = [
    ["Delivered or on track", c(["delivered", "on_track"]), "text-up"],
    ["Missed or off track", c(["missed", "off_track"]), "text-down"],
    ["Not yet due", c(["pending"]), "text-muted"],
    ["Can't verify", c(["unverifiable"]), "text-muted"],
  ];
  return (
    <div className="mb-3 grid grid-cols-2 sm:grid-cols-4 gap-px bg-rule rounded-lg overflow-hidden border border-rule">
      {items.map(([l, n, cls]) => (
        <div key={l} className="bg-surface px-3 py-2">
          <div className={`text-[20px] font-[700] ${n ? cls : "text-faint"}`}>{n}</div>
          <div className="text-[12px] text-muted leading-tight">{l}</div>
        </div>
      ))}
    </div>
  );
}

function PromiseRow({ p }: { p: Promise_ }) {
  const s = STATUS[p.status];
  return (
    <li className="px-4 py-3.5">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className={`text-[12px] font-semibold rounded px-1.5 py-0.5 ${s.cls}`}>{s.label}</span>
        <span className="text-[13px] text-muted">{p.topic ?? p.metric}, said on the {p.said_in} call</span>
      </div>
      <blockquote className="mt-2 pl-3 border-l-2 border-rule text-[14.5px] leading-snug">
        “{p.quote}”
        <span className="text-[12.5px] text-muted not-italic">{p.speaker ? ` ${p.speaker}` : ""}</span>
        <Cite refName={p.ref} page={p.page} />
      </blockquote>
      {p.also_said && p.also_said.length > 0 && (
        <p className="mt-1.5 text-[12.5px] text-muted">
          Also said on the {p.also_said.map((a) => a.said_in).join(" and ")} call{p.also_said.length > 1 ? "s" : ""}
          {p.also_said.map((a) => <Cite key={a.ref + a.page} refName={a.ref} page={a.page} />)}
        </p>
      )}
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[13.5px]">
        <dt className="text-muted">Guided</dt>
        <dd>{p.target_text}{p.period_label ? ` for ${p.period_label}` : ""}</dd>
        {p.actual_text && (<><dt className="text-muted">Reported</dt><dd className="font-medium">{p.actual_text}{p.actual_span ? ` (${p.actual_span})` : ""}</dd></>)}
        {p.detail && (<><dt className="text-muted">Note</dt><dd className="text-muted">{p.detail}</dd></>)}
        {p.model_verdict && (
          <><dt className="text-muted">Model's read</dt>
            <dd><span className="font-medium">{p.model_verdict.replace("_", " ")}</span>. {p.model_reason}{p.model_cite?.map((c) => <Cite key={c} tag={c} />)}</dd></>
        )}
      </dl>
    </li>
  );
}

function CaseList({ title, items }: { title: string; items: { point?: string; cite: string[] }[] }) {
  return (
    <div className="bg-surface rounded-lg border border-rule px-4 py-3">
      <h3 className="text-[14.5px] font-semibold">{title}</h3>
      {items.length === 0 ? <p className="text-[13.5px] text-muted mt-1">Nothing the sources support.</p> : (
        <ul className="mt-1.5 space-y-2 text-[14px] leading-snug list-disc pl-4 marker:text-faint">
          {items.map((b, i) => <li key={i}>{b.point}{b.cite.map((c) => <Cite key={c} tag={c} />)}</li>)}
        </ul>
      )}
    </div>
  );
}

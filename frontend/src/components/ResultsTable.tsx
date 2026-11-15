import type { Check, Metrics } from "../lib/api";
import { crore } from "../lib/format";

function Delta({ v }: { v: number | null | undefined }) {
  if (v == null) return <span className="text-faint">–</span>;
  const c = v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted";
  return <span className={c}>{v > 0 ? "+" : v < 0 ? "−" : ""}{Math.abs(v).toFixed(1)}%</span>;
}

/** Revenue / EBITDA / PBT / PAT for one quarter with QoQ and YoY. Used in feed cards and dossiers. */
export function ResultsTable({ current, qoq, yoy, financial, compact = false }: {
  current: Metrics; qoq: Record<string, number | null>; yoy: Record<string, number | null>; financial: boolean; compact?: boolean;
}) {
  const rows: [string, keyof Metrics, string][] = [
    [financial ? "Total income" : "Revenue", "revenue", "revenue"],
    ["EBITDA", "ebitda", "ebitda"],
    ["PBT", "pbt", "pbt"],
    ["PAT", "pat", "pat"],
  ];
  const pad = compact ? "py-1" : "py-1.5";
  return (
    <table className="w-full text-[13.5px]">
      <thead>
        <tr className="text-muted text-[12px]">
          <th className="text-left font-medium">₹ crore</th>
          <th className="text-right font-medium">Quarter</th>
          <th className="text-right font-medium">QoQ</th>
          <th className="text-right font-medium">YoY</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([lbl, k, dk]) => {
          const val = current[k] as number | null;
          const isE = k === "ebitda";
          return (
            <tr key={k} className="border-t border-rule">
              <td className={`${pad} text-left`}>
                {lbl}
                {isE && val != null && current.ebitda_margin != null && <span className="text-faint text-[12px]"> {current.ebitda_margin.toFixed(1)}% margin</span>}
              </td>
              <td className={`${pad} text-right font-medium`} title={isE ? current.ebitda_note : undefined}>
                {val == null ? <span className="text-faint" title={current.ebitda_note}>{isE && financial ? "n/m" : "–"}</span> : crore(val)}
              </td>
              <td className={`${pad} text-right`}><Delta v={qoq[dk]} /></td>
              <td className={`${pad} text-right`}><Delta v={yoy[dk]} /></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function ChecksLine({ checks }: { checks: Check[] }) {
  if (!checks.length) return null;
  const bad = checks.filter((c) => !c.ok);
  return bad.length === 0 ? (
    <span className="text-muted">Arithmetic checks passed ({checks.map((c) => c.name).join("; ")}).</span>
  ) : (
    <span className="text-warn font-medium">Check failed: {bad.map((c) => `${c.name} (${c.detail})`).join("; ")}. Verify against the filing.</span>
  );
}

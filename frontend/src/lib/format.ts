// Formatting helpers. All times are shown in IST, the market's own clock.

const IST = "Asia/Kolkata";

export const CATEGORY_LABEL: Record<string, string> = {
  results: "Results",
  "M&A": "M&A",
  fund_raise: "Fund raise",
  management_change: "Management change",
  litigation: "Litigation / regulatory",
  insider_trading: "Insider / promoter trade",
  earnings_call: "Earnings call",
  investor_meetings: "Investor meeting",
  credit_rating: "Credit rating",
  dividend: "Dividend",
  bonus_split: "Bonus / split",
  capex: "Capex",
  press_release: "Press release",
  postal_ballot: "Postal ballot",
  agm_egm: "AGM / EGM",
  pledging: "Promoter pledge",
  unclassified: "Routine filing",
};

// Natural phrases for common category + sub-type pairs.
const COMBINED: Record<string, string> = {
  "results:outcome": "Results declared",
  "results:intimation": "Results date set",
  "results:newspaper_ad": "Results newspaper ad",
  "results:presentation": "Results presentation",
  "results:press_release": "Results press release",
  "management_change:kmp_join": "Senior management appointment",
  "management_change:kmp_exit": "Senior management exit",
  "management_change:director_join": "Board appointment",
  "management_change:director_exit": "Board exit",
  "management_change:other_join": "Management appointment",
  "management_change:other_exit": "Management exit",
  "management_change:kmp_retire": "Senior management retirement",
  "management_change:kmp_reappoint": "Senior re-appointment",
  "management_change:director_retire": "Board retirement",
  "management_change:director_reappoint": "Board re-appointment",
  "management_change:other_retire": "Management retirement",
  "management_change:other_reappoint": "Re-appointment",
  "management_change:unspecified": "Management change, details in filing",
  "litigation:regulatory": "Regulatory action",
  "litigation:legal": "Litigation",
  "earnings_call:transcript": "Earnings call transcript",
  "earnings_call:notice": "Earnings call scheduled",
  "earnings_call:recording": "Earnings call recording",
  "credit_rating:downgrade": "Credit rating downgrade",
  "credit_rating:upgrade": "Credit rating upgrade",
  "credit_rating:reaffirm": "Credit rating reaffirmed",
  "press_release:order_win": "Order win",
  "fund_raise:buyback": "Buyback",
  "fund_raise:debt": "Debt raise",
  "fund_raise:equity": "Equity raise",
  "M&A:subsidiary": "Subsidiary set-up or investment",
  "pledging:create": "Promoter pledge created",
  "pledging:release": "Promoter pledge released",
};

export function categoryLabel(cat: string, sub?: string): string {
  return COMBINED[`${cat}:${sub}`] ?? CATEGORY_LABEL[cat] ?? cat;
}

export function relTime(iso: string, now = Date.now()): string {
  const t = new Date(iso).getTime();
  const m = Math.round((now - t) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 7) return `${d}d ago`;
  return absDate(iso);
}

export function absTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: IST, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  }) + " IST";
}

export function absDate(isoOrDate: string): string {
  const d = isoOrDate.length === 10 ? new Date(isoOrDate + "T12:00:00+05:30") : new Date(isoOrDate);
  return d.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", weekday: "short" });
}

export function inr(n: number | null | undefined, digits = 2): string {
  if (n == null) return "–";
  return "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(n: number | null | undefined, digits = 1): string {
  if (n == null) return "–";
  const s = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${s}${Math.abs(n).toFixed(digits)}%`;
}

export function compactVol(n: number | null | undefined): string {
  if (n == null) return "–";
  if (n >= 1e7) return (n / 1e7).toFixed(2) + " cr";
  if (n >= 1e5) return (n / 1e5).toFixed(1) + " L";
  return n.toLocaleString("en-IN");
}

/** ₹ crore with Indian grouping; one decimal under 1,000 crore. */
export function crore(n: number | null | undefined): string {
  if (n == null) return "–";
  const d = Math.abs(n) >= 1000 ? 0 : 1;
  return n.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
}

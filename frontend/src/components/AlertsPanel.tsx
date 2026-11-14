import { useEffect } from "react";
import { api } from "../lib/api";
import { relTime } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const KIND: Record<string, string> = { price: "Price", volume: "Volume", announcement: "Filing" };

export function AlertsPanel({ onClose }: { onClose: () => void }) {
  const { data, error } = useAsync(() => api.alerts(), []);

  // Opening the panel counts as reading the alerts.
  useEffect(() => { if (data && data.unseen > 0) api.alertsSeen(); }, [data]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Alerts">
      <button className="absolute inset-0 bg-ink/30" aria-label="Close alerts" onClick={onClose} />
      <div className="absolute right-0 top-0 h-full w-full sm:w-[420px] bg-surface border-l border-rule flex flex-col">
        <div className="flex items-center justify-between px-4 h-14 border-b border-rule">
          <h2 className="text-[17px] font-semibold">Alerts</h2>
          <button onClick={onClose} className="text-accent font-semibold text-[14.5px]">Done</button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {error && <p className="p-4 text-down text-[14px]">Couldn't load alerts: {error}</p>}
          {data && data.alerts.length === 0 && (
            <p className="p-4 text-[14px] text-muted">No alerts yet. Set thresholds under Alerts & data.</p>
          )}
          <ul className="divide-y divide-rule">
            {data?.alerts.map((a) => (
              <li key={a.id} className={`px-4 py-3 ${a.seen ? "" : "bg-accent-wash/50"}`}>
                <div className="flex items-baseline justify-between text-[12.5px] text-muted">
                  <span>{KIND[a.kind]}</span><span>{relTime(a.created_at)}</span>
                </div>
                <p className="text-[14.5px] leading-snug mt-0.5">{a.message}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

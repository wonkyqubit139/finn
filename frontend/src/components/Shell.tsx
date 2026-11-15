import type { ReactNode } from "react";

export type Route = "feed" | "portfolio" | "research" | "settings";

const NAV: { id: Route; label: string; icon: ReactNode }[] = [
  {
    id: "feed", label: "Feed",
    icon: <path d="M4 6h16M4 12h10M4 18h13" strokeLinecap="round" />,
  },
  {
    id: "portfolio", label: "Portfolio",
    icon: <path d="M4 19V9m5.5 10V5M15 19v-7m5.5 7V8" strokeLinecap="round" />,
  },
  {
    id: "research", label: "Research",
    icon: <><circle cx="10.5" cy="10.5" r="6" /><path d="m15 15 5 5" strokeLinecap="round" /></>,
  },
  {
    id: "settings", label: "Alerts & data",
    icon: <><circle cx="12" cy="12" r="3" /><path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1m-8.6 8.6-2.1 2.1" strokeLinecap="round" /></>,
  },
];

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      {children}
    </svg>
  );
}

export function Shell({ route, go, unseen, onBell, children }: {
  route: Route; go: (r: Route) => void; unseen: number; onBell: () => void; children: ReactNode;
}) {
  return (
    <div className="min-h-dvh md:flex">
      {/* Desktop rail */}
      <nav className="hidden md:flex md:flex-col md:w-56 md:shrink-0 md:sticky md:top-0 md:h-dvh border-r border-rule px-4 py-6"
           aria-label="Main">
        <div className="px-2 mb-8">
          <div className="text-[22px] font-[750] tracking-[-0.02em]">FINN</div>
          <div className="text-[12.5px] text-muted">Your portfolio, filtered</div>
        </div>
        {NAV.map((n) => (
          <button key={n.id} onClick={() => go(n.id)} aria-current={route === n.id ? "page" : undefined}
                  className={`flex items-center gap-3 px-2 py-2 rounded-md text-[14.5px] text-left ${route === n.id
                    ? "bg-surface font-semibold text-ink" : "text-muted hover:text-ink"}`}>
            <Icon>{n.icon}</Icon>{n.label}
          </button>
        ))}
        <button onClick={onBell} className="mt-auto flex items-center gap-3 px-2 py-2 text-[14.5px] text-muted hover:text-ink">
          <BellIcon />Alerts{unseen > 0 && <Badge n={unseen} />}
        </button>
      </nav>

      <div className="flex-1 min-w-0">
        {/* Mobile header */}
        <header className="md:hidden sticky top-0 z-20 bg-ground/95 backdrop-blur border-b border-rule">
          <div className="flex items-center justify-between px-4 h-12">
            <span className="text-[18px] font-[750] tracking-[-0.02em]">FINN</span>
            <button onClick={onBell} aria-label={`Alerts, ${unseen} unread`} className="relative p-2 -mr-2 text-ink">
              <BellIcon />
              {unseen > 0 && <span className="absolute top-1 right-0.5"><Badge n={unseen} /></span>}
            </button>
          </div>
        </header>

        <main className="mx-auto max-w-[760px] pb-24 md:pb-12 md:px-8 pt-4 md:pt-8">{children}</main>

        {/* Mobile tab bar */}
        <nav className="md:hidden fixed bottom-0 inset-x-0 z-20 bg-surface border-t border-rule pb-safe" aria-label="Main">
          <div className="grid grid-cols-4">
            {NAV.map((n) => (
              <button key={n.id} onClick={() => go(n.id)} aria-current={route === n.id ? "page" : undefined}
                      className={`flex flex-col items-center gap-0.5 pt-2 pb-2.5 text-[11.5px] ${route === n.id
                        ? "text-ink font-semibold" : "text-faint"}`}>
                <Icon>{n.icon}</Icon>{n.label}
              </button>
            ))}
          </div>
        </nav>
      </div>
    </div>
  );
}

function BellIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16Zm4 4h4" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function Badge({ n }: { n: number }) {
  return (
    <span className="inline-flex min-w-[18px] h-[18px] px-1 items-center justify-center rounded-full bg-accent text-white text-[11px] font-semibold">
      {n > 99 ? "99+" : n}
    </span>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Shell, type Route } from "./components/Shell";
import { AlertsPanel } from "./components/AlertsPanel";
import { FeedScreen } from "./screens/Feed";
import { PortfolioScreen } from "./screens/Portfolio";
import { SettingsScreen } from "./screens/Settings";
import { ResearchScreen } from "./screens/Research";
import { DossierScreen } from "./screens/Dossier";
import { api } from "./lib/api";

const ROUTES: Route[] = ["feed", "portfolio", "research", "settings"];
function parseHash(): { route: Route; symbol: string | null } {
  const m = location.hash.match(/^#\/research\/([A-Za-z0-9&-]+)/);
  if (m) return { route: "research", symbol: decodeURIComponent(m[1]).toUpperCase() };
  return { route: ROUTES.find((r) => location.hash === `#/${r}`) ?? "feed", symbol: null };
}

export default function App() {
  const [{ route, symbol }, setLoc] = useState(parseHash);
  const [bell, setBell] = useState(false);
  const [unseen, setUnseen] = useState(0);
  const [epoch, setEpoch] = useState(0); // bump to make screens refetch after data changes

  useEffect(() => {
    const h = () => { setLoc(parseHash()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);

  const loadUnseen = useCallback(() => { api.alerts().then((a) => setUnseen(a.unseen)).catch(() => {}); }, []);
  useEffect(loadUnseen, [loadUnseen, epoch]);

  // "Since last visit": record this visit after a short dwell, so the next
  // visit's window starts here.
  useEffect(() => {
    const t = setTimeout(() => { api.markSeen().catch(() => {}); }, 8000);
    return () => clearTimeout(t);
  }, []);

  const go = (r: Route) => { location.hash = `#/${r}`; };
  const openResearch = (sym: string) => { location.hash = `#/research/${encodeURIComponent(sym)}`; };
  const changed = () => setEpoch((e) => e + 1);

  return (
    <Shell route={route} go={go} unseen={unseen} onBell={() => setBell(true)}>
      {route === "feed" && <FeedScreen key={epoch} onDataChanged={changed} openResearch={openResearch} />}
      {route === "portfolio" && <PortfolioScreen key={epoch} openResearch={openResearch} />}
      {route === "research" && !symbol && <ResearchScreen open={openResearch} />}
      {route === "research" && symbol && <DossierScreen key={symbol} symbol={symbol} back={() => go("research")} />}
      {route === "settings" && <SettingsScreen onDataChanged={changed} />}
      {bell && <AlertsPanel onClose={() => { setBell(false); loadUnseen(); }} />}
    </Shell>
  );
}

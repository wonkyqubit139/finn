import { useCallback, useEffect, useState } from "react";
import { Shell, type Route } from "./components/Shell";
import { AlertsPanel } from "./components/AlertsPanel";
import { FeedScreen } from "./screens/Feed";
import { PortfolioScreen } from "./screens/Portfolio";
import { SettingsScreen } from "./screens/Settings";
import { api } from "./lib/api";

const ROUTES: Route[] = ["feed", "portfolio", "settings"];
const fromHash = (): Route => (ROUTES.find((r) => location.hash === `#/${r}`) ?? "feed");

export default function App() {
  const [route, setRoute] = useState<Route>(fromHash);
  const [bell, setBell] = useState(false);
  const [unseen, setUnseen] = useState(0);
  const [epoch, setEpoch] = useState(0); // bump to make screens refetch after data changes

  useEffect(() => {
    const h = () => setRoute(fromHash());
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

  const go = (r: Route) => { location.hash = `#/${r}`; setRoute(r); window.scrollTo(0, 0); };
  const changed = () => setEpoch((e) => e + 1);

  return (
    <Shell route={route} go={go} unseen={unseen} onBell={() => setBell(true)}>
      {route === "feed" && <FeedScreen key={epoch} onDataChanged={changed} />}
      {route === "portfolio" && <PortfolioScreen key={epoch} />}
      {route === "settings" && <SettingsScreen onDataChanged={changed} />}
      {bell && <AlertsPanel onClose={() => { setBell(false); loadUnseen(); }} />}
    </Shell>
  );
}

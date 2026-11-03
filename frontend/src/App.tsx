import { useEffect, useState } from "react";
import { HistoryPage } from "./pages/HistoryPage";
import { InterviewPage } from "./pages/InterviewPage";
import { ReportPage } from "./pages/ReportPage";
import { SetupPage } from "./pages/SetupPage";

type Route =
  | { page: "setup" }
  | { page: "history" }
  | { page: "interview"; sessionId: string }
  | { page: "report"; sessionId: string };

function parseHash(hash: string): Route {
  if (hash === "#/history") return { page: "history" };
  const match = hash.match(/^#\/sessions\/([\w-]+)(\/report)?$/);
  if (!match) return { page: "setup" };
  return { page: match[2] ? "report" : "interview", sessionId: match[1] };
}

export function navigate(path: string): void {
  window.location.hash = path;
}

export function App() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  if (route.page === "history") return <HistoryPage />;
  if (route.page === "report") {
    return <ReportPage key={route.sessionId} sessionId={route.sessionId} />;
  }
  return route.page === "interview" ? (
    <InterviewPage key={route.sessionId} sessionId={route.sessionId} />
  ) : (
    <SetupPage />
  );
}

import { useEffect, useState } from "react";
import { InterviewPage } from "./pages/InterviewPage";
import { SetupPage } from "./pages/SetupPage";

type Route = { page: "setup" } | { page: "interview"; sessionId: string };

function parseHash(hash: string): Route {
  const match = hash.match(/^#\/sessions\/([\w-]+)$/);
  return match ? { page: "interview", sessionId: match[1] } : { page: "setup" };
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

  return route.page === "interview" ? (
    <InterviewPage key={route.sessionId} sessionId={route.sessionId} />
  ) : (
    <SetupPage />
  );
}

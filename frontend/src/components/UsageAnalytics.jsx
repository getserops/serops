import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { startUsageAnalytics, trackPage } from "../utils/usageAnalytics";

// Reports the name of each page shown, on instances whose operator turned
// usage counting on (a public demo). Renders nothing; does nothing otherwise.
export default function UsageAnalytics() {
  const { pathname } = useLocation();
  const [on, setOn] = useState(false);
  useEffect(() => {
    let alive = true;
    startUsageAnalytics().then((started) => { if (alive) setOn(started); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (on) trackPage(pathname);
  }, [on, pathname]);
  return null;
}

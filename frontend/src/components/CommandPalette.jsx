import React, { useEffect, useMemo, useRef, useState } from "react";
import { Modal } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FaSearch, FaFileAlt, FaBolt, FaExclamationCircle, FaProjectDiagram, FaMoon, FaSun, FaDesktop } from "react-icons/fa";
import dataService from "../services/data.service";
import InvestigationService from "../services/investigation.service";
import { applyTheme } from "../utils/theme";
import { isDemoUser } from "../utils/demo";
import "./CommandPalette.css";

export const OPEN_EVENT = "serops:open-command-palette";

// Every page reachable from the sidebar, named the same way.
const PAGES = [
  ["/dash", "nav.dashboard"],
  ["/dash/issues", "nav.issues"],
  ["/dash/data", "nav.data"],
  ["/dash/investigate", "nav.investigate"],
  ["/dash/chat", "nav.aiChat"],
  ["/dash/projects", "nav.projects"],
  ["/dash/notifications", "nav.notifications"],
  ["/dash/profile", "nav.profile"],
  ["/dash/settings", "nav.settings"],
  ["/dash/settings/team", "settings.team.title"],
  ["/dash/settings/delivery", "settings.delivery.title"],
  ["/dash/settings/routing-rules", "settings.routing.title"],
  ["/dash/settings/ai", "settings.ai.title"],
  ["/dash/settings/sentinel", "sentinel.title"],
  ["/dash/settings/data", "settings.data.title"],
  ["/dash/settings/integrations", "globalIntegrations.title"],
  ["/dash/settings/traces", "traces.settings.menuLabel"],
  ["/dash/settings/clusters", "clusters.menuLabel"],
  ["/dash/settings/security", "settings.security.title"],
  ["/dash/settings/audit", "auditLog.title"],
];

const matches = (label, query) => {
  const hay = label.toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
};

const setTheme = (theme) => {
  let settings = {};
  try { settings = JSON.parse(localStorage.getItem("seropsSettings") || "{}"); } catch { /* keep defaults */ }
  const next = { ...settings, theme };
  try { localStorage.setItem("seropsSettings", JSON.stringify(next)); } catch { /* private mode */ }
  applyTheme(theme);
  window.dispatchEvent(new CustomEvent("settingsChanged", { detail: next }));
};

/**
 * ⌘K / Ctrl+K: jump to any page, open issue or project, or run an action,
 * from the keyboard.
 */
const CommandPalette = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef(null);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onOpen);
    };
  }, []);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(id);
  }, [query]);

  const { data: issueData } = useQuery({
    queryKey: ["palette-issues", debounced],
    queryFn: () => dataService.getIssues({ search: debounced, status: "OPEN", page_size: 5 }),
    enabled: open && debounced.length >= 2,
    staleTime: 30 * 1000,
  });
  const { data: scope } = useQuery({
    queryKey: ["palette-scope"],
    queryFn: () => InvestigationService.options(),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

  const items = useMemo(() => {
    const q = query.trim();
    const out = [];
    const add = (group, list) => list.forEach((item) => out.push({ ...item, group }));
    add(t("palette.pages"), PAGES
      .map(([path, key]) => ({ id: `page:${path}`, label: t(key), hint: path.replace("/dash", "") || "/", icon: FaFileAlt, run: () => navigate(path) }))
      .filter((i) => !q || matches(i.label, q)));
    const actions = [
      !isDemoUser() && { id: "act:investigate", label: t("palette.newInvestigation"), icon: FaBolt, run: () => navigate("/dash/investigate") },
      { id: "act:dark", label: t("palette.themeDark"), icon: FaMoon, run: () => setTheme("dark") },
      { id: "act:light", label: t("palette.themeLight"), icon: FaSun, run: () => setTheme("light") },
      { id: "act:system", label: t("palette.themeSystem"), icon: FaDesktop, run: () => setTheme("system") },
    ].filter(Boolean);
    add(t("palette.actions"), actions.filter((i) => !q || matches(i.label, q)));
    if (q) {
      add(t("palette.issues"), (issueData?.results || []).map((issue) => ({
        id: `issue:${issue.id}`, label: issue.description, hint: issue.component, icon: FaExclamationCircle,
        run: () => navigate(`/dash/issues?id=${issue.id}`),
      })));
      add(t("palette.projects"), (scope?.projects || [])
        .filter((p) => matches(p.name, q))
        .map((p) => ({ id: `project:${p.id}`, label: p.name, icon: FaProjectDiagram, run: () => navigate(`/dash/projects/${p.id}`) })));
    }
    return out;
  }, [query, issueData, scope, t, navigate]);

  useEffect(() => { setActive(0); }, [query]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const close = () => { setOpen(false); setQuery(""); };
  const run = (item) => { close(); item.run(); };

  const onInputKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(items.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter" && items[active]) { e.preventDefault(); run(items[active]); }
  };

  let lastGroup = null;
  return (
    <Modal show={open} onHide={close} dialogClassName="command-palette" aria-label={t("palette.title")} restoreFocus>
      <div className="command-palette-search">
        <FaSearch aria-hidden="true" />
        <input
          autoFocus
          role="combobox"
          aria-expanded="true"
          aria-controls="command-palette-list"
          aria-activedescendant={items[active] ? `cp-${active}` : undefined}
          aria-label={t("palette.title")}
          placeholder={t("palette.placeholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onInputKey}
        />
        <kbd>Esc</kbd>
      </div>
      <ul id="command-palette-list" role="listbox" className="command-palette-list" ref={listRef}>
        {items.length === 0 && <li className="command-palette-empty">{t("palette.noResults")}</li>}
        {items.map((item, i) => {
          const header = item.group !== lastGroup ? item.group : null;
          lastGroup = item.group;
          const Icon = item.icon;
          return (
            <React.Fragment key={item.id}>
              {header && <li role="presentation" className="command-palette-group">{header}</li>}
              <li
                id={`cp-${i}`}
                data-index={i}
                role="option"
                aria-selected={i === active}
                className={`command-palette-item ${i === active ? "is-active" : ""}`}
                onMouseMove={() => setActive(i)}
                onClick={() => run(item)}
              >
                <Icon aria-hidden="true" className="command-palette-icon" />
                <span className="command-palette-label">{item.label}</span>
                {item.hint && <span className="command-palette-hint">{item.hint}</span>}
              </li>
            </React.Fragment>
          );
        })}
      </ul>
    </Modal>
  );
};

export default CommandPalette;

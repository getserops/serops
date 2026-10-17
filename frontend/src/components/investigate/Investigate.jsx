import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FaCheckCircle, FaCircleNotch, FaExclamationTriangle, FaRegCircle, FaSearch } from "react-icons/fa";
import InvestigationService from "../../services/investigation.service";
import { isDemoUser } from "../../utils/demo";
import { describeRequestError } from "../../utils/apiError";
import { PRESETS, clampWindow, fromLocalInput, toLocalInput, validateWindow, MINUTE } from "./window";
import "./Investigate.css";

const ACTIVE = ["queued", "collecting", "analyzing"];
const STEPS = ["queued", "collecting", "analyzing", "done"];
const POLL_MS = 2500;

const STATUS_CHIP = {
  queued: "ds-chip-neutral",
  collecting: "ds-chip-info",
  analyzing: "ds-chip-info",
  done: "ds-chip-ok",
  no_data: "ds-chip-warn",
  failed: "ds-chip-err",
};

// Production first: an investigation is most often about production.
export function defaultEnvironment(project) {
  const envs = project?.environments || [];
  return envs.find((e) => /^prod(uction)?$/i.test(e.name)) || envs[0] || null;
}

function currentUserRole() {
  try {
    return JSON.parse(localStorage.getItem("user") || "{}").role || "viewer";
  } catch {
    return "viewer";
  }
}

const formatWhen = (iso) => (iso ? new Date(iso).toLocaleString() : "—");

function RunProgress({ run, t }) {
  const reached = run.status === "done" ? STEPS.length : STEPS.indexOf(run.status) + 1;
  const counts = run.counts || {};
  return (
    <div className="ds-card ds-card-elevated investigate-run" aria-live="polite">
      <div className="ds-card-body">
        <div className="investigate-run-head">
          <span className={`ds-chip ${STATUS_CHIP[run.status] || "ds-chip-neutral"}`}>
            {t(`investigate.status.${run.status}`)}
          </span>
          <span className="investigate-run-scope">
            {run.project?.name}
            {run.environment ? ` · ${run.environment.name}` : ""}
            {run.services?.length ? ` · ${run.services.join(", ")}` : ""}
          </span>
          <span className="investigate-run-window">
            {formatWhen(run.window_start)} → {formatWhen(run.window_end)}
          </span>
        </div>

        {(ACTIVE.includes(run.status) || run.status === "done") && (
          <ol className="investigate-steps">
            {STEPS.map((step, i) => {
              const state = i < reached - 1 || run.status === "done" ? "done" : i === reached - 1 ? "active" : "todo";
              return (
                <li key={step} className={`investigate-step is-${state}`}>
                  {state === "done" ? <FaCheckCircle /> : state === "active" ? <FaCircleNotch className="spin" /> : <FaRegCircle />}
                  <span>{t(`investigate.steps.${step}`)}</span>
                </li>
              );
            })}
          </ol>
        )}

        {Object.keys(counts).length > 0 && (
          <div className="investigate-counts">
            {["logs", "metrics", "traces", "code_changes", "cicd"].map((k) => (
              <span key={k} className="ds-chip ds-chip-neutral">
                {t(`investigate.counts.${k}`, { count: counts[k] || 0 })}
              </span>
            ))}
          </div>
        )}

        {run.status === "done" && (
          <div className="investigate-result">
            <span>
              {run.issue_count ? t("investigate.result.issues", { count: run.issue_count }) : t("investigate.result.noIssues")}
            </span>
            {run.batch_id && (
              <Link className="ds-btn ds-btn-primary ds-btn-sm" to={`/dash/data/details/${run.batch_id}`}>
                {t("investigate.result.open")}
              </Link>
            )}
          </div>
        )}
        {run.status === "no_data" && <p className="investigate-note">{t("investigate.result.noData")}</p>}
        {run.status === "failed" && (
          <p className="investigate-note is-error">
            <FaExclamationTriangle /> {run.error || t("investigate.result.failed")}
          </p>
        )}
      </div>
    </div>
  );
}

const Investigate = () => {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const demo = isDemoUser();
  const canRun = !demo && currentUserRole() !== "viewer";

  const [options, setOptions] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [projectId, setProjectId] = useState("");
  const [environmentId, setEnvironmentId] = useState("");
  const [deploymentId, setDeploymentId] = useState("");
  const [services, setServices] = useState([]);
  const [preset, setPreset] = useState("30m");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [hint, setHint] = useState("");
  const [notifyRouting, setNotifyRouting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [run, setRun] = useState(null);
  const [history, setHistory] = useState({ results: [], count: 0 });

  const limits = useMemo(() => {
    const l = options?.limits || {};
    return { minMinutes: l.min_window_minutes || 5, maxHours: l.max_window_hours || 6, maxLookbackDays: l.max_lookback_days || 30 };
  }, [options]);
  const project = options?.projects.find((p) => String(p.id) === String(projectId));
  const deployments = (project?.deployments || []).filter(
    (d) => !environmentId || !d.environment_id || String(d.environment_id) === String(environmentId),
  );

  const applyPreset = useCallback((key, proj) => {
    setPreset(key);
    const now = new Date();
    let s;
    if (key === "deploy") {
      if (!proj?.last_deploy_at) return;
      s = new Date(new Date(proj.last_deploy_at) - 5 * MINUTE);
    } else {
      s = new Date(now - PRESETS.find((p) => p.key === key).minutes * MINUTE);
    }
    const w = clampWindow(s, now, limits, now);
    setStart(toLocalInput(w.start));
    setEnd(toLocalInput(w.end));
  }, [limits]);

  const loadHistory = useCallback(() => {
    InvestigationService.list({ limit: 20 })
      .then((data) => {
        setHistory(data);
        // One source of truth on screen: the run card follows its history row.
        setRun((cur) => (cur && data.results.find((r) => r.id === cur.id)) || cur);
      })
      .catch(() => {});
  }, []);

  // Options, then the prefill from the URL ("Analyze this deploy", "Re-run").
  useEffect(() => {
    InvestigationService.options()
      .then((data) => {
        setOptions(data);
        const proj = data.projects.find((p) => String(p.id) === params.get("project_id")) || data.projects[0];
        if (!proj) return;
        setProjectId(String(proj.id));
        const envByName = proj.environments.find((e) => e.name === params.get("environment"));
        const dep = proj.deployments.find((d) => String(d.id) === params.get("deployment_id"));
        const envId = params.get("environment_id") || envByName?.id || dep?.environment_id || defaultEnvironment(proj)?.id || "";
        setEnvironmentId(envId ? String(envId) : "");
        setDeploymentId(dep ? String(dep.id) : "");
        const wanted = (params.get("services") || "").split(",").filter((s) => proj.services.includes(s));
        setServices(wanted);
        setHint((params.get("hint") || "").slice(0, data.limits.hint_max_length));
        const s = params.get("start") ? new Date(params.get("start")) : null;
        const e = params.get("end") ? new Date(params.get("end")) : new Date();
        if (s && !Number.isNaN(s.getTime()) && !Number.isNaN(e.getTime())) {
          const w = clampWindow(s, e, {
            minMinutes: data.limits.min_window_minutes, maxHours: data.limits.max_window_hours,
          });
          setPreset("custom");
          setStart(toLocalInput(w.start));
          setEnd(toLocalInput(w.end));
        } else {
          const now = new Date();
          setStart(toLocalInput(new Date(now - 30 * MINUTE)));
          setEnd(toLocalInput(now));
        }
      })
      .catch((err) => setLoadError(describeRequestError(err, t("investigate.loadFailed"))));
    loadHistory();
    // Prefill once, from the URL the page was opened with.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Follow the active run until it settles.
  useEffect(() => {
    if (!run || !ACTIVE.includes(run.status)) return undefined;
    const timer = setInterval(() => {
      InvestigationService.get(run.id)
        .then((fresh) => {
          setRun(fresh);
          if (!ACTIVE.includes(fresh.status)) loadHistory();
        })
        .catch(() => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [run, loadHistory]);

  const onProjectChange = (id) => {
    setProjectId(id);
    const proj = options.projects.find((p) => String(p.id) === id);
    const env = defaultEnvironment(proj);
    setEnvironmentId(env ? String(env.id) : "");
    setDeploymentId("");
    setServices([]);
    if (preset === "deploy") applyPreset("30m", proj);
  };

  const toggleService = (name) =>
    setServices((cur) => (cur.includes(name) ? cur.filter((s) => s !== name) : [...cur, name]));

  const submit = async (e) => {
    e.preventDefault();
    setFormError("");
    const s = fromLocalInput(start);
    const en = fromLocalInput(end);
    const problem = validateWindow(s, en, limits);
    if (problem) {
      setFormError(t(`investigate.window.${problem}`, limits));
      return;
    }
    setSubmitting(true);
    try {
      const created = await InvestigationService.create({
        project_id: Number(projectId),
        environment_id: environmentId ? Number(environmentId) : null,
        deployment_id: deploymentId ? Number(deploymentId) : null,
        services,
        window_start: s.toISOString(),
        window_end: en.toISOString(),
        hint: hint.trim(),
        notify_routing: notifyRouting,
      });
      setRun(created);
      loadHistory();
    } catch (err) {
      setFormError(err.response?.data?.message || describeRequestError(err, t("investigate.startFailed")));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="investigate-page">
      <div className="ds-section-header">
        <div className="ds-section-header-icon"><FaSearch /></div>
        <div className="ds-section-header-body">
          <h1 className="ds-section-header-title">{t("investigate.title")}</h1>
          <p className="ds-section-header-subtitle">{t("investigate.subtitle")}</p>
        </div>
      </div>

      {loadError && <div className="investigate-note is-error">{loadError}</div>}
      {!canRun && (
        <div className="investigate-banner">{demo ? t("investigate.demoNotice") : t("investigate.viewerNotice")}</div>
      )}

      {options && options.projects.length === 0 && (
        <div className="ds-card"><div className="ds-empty-state">
          <p className="ds-empty-state-title">{t("investigate.noProjects")}</p>
          <Link to="/dash/projects">{t("investigate.createProject")}</Link>
        </div></div>
      )}

      {options && options.projects.length > 0 && (
        <form className="ds-card ds-card-elevated investigate-form" onSubmit={submit}>
          <div className="ds-card-body">
            <div className="investigate-grid">
              <label className="investigate-field">
                <span className="ds-label">{t("investigate.project")}</span>
                <select className="ds-input" value={projectId} onChange={(e) => onProjectChange(e.target.value)}>
                  {options.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </label>
              <label className="investigate-field">
                <span className="ds-label">{t("investigate.environment")}</span>
                <select className="ds-input" value={environmentId}
                        onChange={(e) => { setEnvironmentId(e.target.value); setDeploymentId(""); }}>
                  <option value="">{t("investigate.anyEnvironment")}</option>
                  {(project?.environments || []).map((env) => <option key={env.id} value={env.id}>{env.display_name}</option>)}
                </select>
              </label>
              <label className="investigate-field">
                <span className="ds-label">{t("investigate.deployment")}</span>
                <select className="ds-input" value={deploymentId} onChange={(e) => setDeploymentId(e.target.value)}>
                  <option value="">{t("investigate.allDeployments")}</option>
                  {deployments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </label>
            </div>

            {project?.services.length > 0 && (
              <fieldset className="investigate-field">
                <legend className="ds-label">{t("investigate.services")}</legend>
                <div className="investigate-chips">
                  {project.services.map((name) => (
                    <button type="button" key={name} aria-pressed={services.includes(name)}
                            className={`investigate-chip ${services.includes(name) ? "is-on" : ""}`}
                            onClick={() => toggleService(name)}>
                      {name}
                    </button>
                  ))}
                </div>
                <span className="ds-help">{services.length ? t("investigate.servicesSome", { count: services.length }) : t("investigate.servicesAll")}</span>
              </fieldset>
            )}

            <fieldset className="investigate-field">
              <legend className="ds-label">{t("investigate.window.label")}</legend>
              <div className="investigate-chips">
                {PRESETS.map((p) => (
                  <button type="button" key={p.key} aria-pressed={preset === p.key}
                          className={`investigate-chip ${preset === p.key ? "is-on" : ""}`}
                          onClick={() => applyPreset(p.key, project)}>
                    {t(`investigate.window.presets.${p.key}`)}
                  </button>
                ))}
                <button type="button" aria-pressed={preset === "deploy"} disabled={!project?.last_deploy_at}
                        title={project?.last_deploy_at ? formatWhen(project.last_deploy_at) : t("investigate.window.noDeploy")}
                        className={`investigate-chip ${preset === "deploy" ? "is-on" : ""}`}
                        onClick={() => applyPreset("deploy", project)}>
                  {t("investigate.window.presets.deploy")}
                </button>
              </div>
              <div className="investigate-grid">
                <label className="investigate-field">
                  <span className="ds-label">{t("investigate.window.from")}</span>
                  <input type="datetime-local" className="ds-input" value={start}
                         onChange={(e) => { setStart(e.target.value); setPreset("custom"); }} />
                </label>
                <label className="investigate-field">
                  <span className="ds-label">{t("investigate.window.to")}</span>
                  <input type="datetime-local" className="ds-input" value={end}
                         onChange={(e) => { setEnd(e.target.value); setPreset("custom"); }} />
                </label>
              </div>
              <span className="ds-help">{t("investigate.window.help", limits)}</span>
            </fieldset>

            <label className="investigate-field">
              <span className="ds-label">{t("investigate.hint.label")}</span>
              <textarea className="ds-input ds-textarea" value={hint} maxLength={options.limits.hint_max_length}
                        placeholder={t("investigate.hint.placeholder")} onChange={(e) => setHint(e.target.value)} />
              <span className="ds-help">{t("investigate.hint.help", { count: options.limits.hint_max_length - hint.length })}</span>
            </label>

            <label className="investigate-check">
              <input type="checkbox" checked={notifyRouting} onChange={(e) => setNotifyRouting(e.target.checked)} />
              <span>{t("investigate.notifyRouting")}</span>
            </label>

            {formError && <div className="investigate-note is-error" role="alert">{formError}</div>}

            <div className="investigate-actions">
              <button type="submit" className="ds-btn ds-btn-primary"
                      disabled={!canRun || submitting || (run && ACTIVE.includes(run.status))}>
                {submitting ? <FaCircleNotch className="spin" /> : <FaSearch />} {t("investigate.run")}
              </button>
              <span className="ds-help">{t("investigate.chatDifference")}</span>
            </div>
          </div>
        </form>
      )}

      {run && <RunProgress run={run} t={t} />}

      <div className="ds-card investigate-history">
        <div className="ds-card-header">{t("investigate.history.title")}</div>
        {history.results.length === 0 ? (
          <div className="ds-empty-state"><p className="ds-empty-state-body">{t("investigate.history.empty")}</p></div>
        ) : (
          <div className="investigate-table-wrap">
            <table className="investigate-table table-stack">
              <thead>
                <tr>
                  <th>{t("investigate.history.started")}</th>
                  <th>{t("investigate.history.scope")}</th>
                  <th>{t("investigate.history.window")}</th>
                  <th>{t("investigate.history.by")}</th>
                  <th>{t("investigate.history.status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {history.results.map((r) => (
                  <tr key={r.id}>
                    <td>{formatWhen(r.created_at)}</td>
                    <td>
                      {r.project?.name}{r.environment ? ` · ${r.environment.name}` : ""}
                      {r.hint && <div className="investigate-hint" title={r.hint}>“{r.hint}”</div>}
                    </td>
                    <td className="investigate-nowrap">{formatWhen(r.window_start)}<br />{formatWhen(r.window_end)}</td>
                    <td>{r.requested_by?.name || "—"}</td>
                    <td>
                      <span className={`ds-chip ${STATUS_CHIP[r.status] || "ds-chip-neutral"}`}>{t(`investigate.status.${r.status}`)}</span>
                      {r.status === "done" && <div className="ds-help">{t("investigate.result.issues", { count: r.issue_count || 0 })}</div>}
                    </td>
                    <td>
                      {r.batch_id && r.status === "done"
                        ? <Link to={`/dash/data/details/${r.batch_id}`}>{t("investigate.result.open")}</Link>
                        : ACTIVE.includes(r.status)
                          ? <button type="button" className="ds-btn ds-btn-ghost ds-btn-sm" onClick={() => setRun(r)}>{t("investigate.history.follow")}</button>
                          : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default Investigate;

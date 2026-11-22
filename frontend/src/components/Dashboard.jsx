import React from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "./Sidebar";
import Navbar from "./Navbar";
import DashboardService from "../services/dash.service";
import dataService from "../services/data.service";
import { useCluster } from "../context/ClusterContext";
import useFilterUrlSync from "../hooks/useFilterUrlSync";
import { useQuery } from "@tanstack/react-query";
import { FaExclamationTriangle, FaExclamationCircle } from "react-icons/fa";
import { useMediaQuery } from "@mui/material";
import { Search } from "lucide-react";
import PageHeader from "./PageHeader";
import "./Dashboard.css";

import HealthScoreCard from "./HealthScoreCard";
import TrendAnalysisChart from "./TrendAnalysisChart";
import RootCausePie from "./RootCausePie";
import ServiceHealthHeatmap from "./ServiceHealthHeatmap";
import RecentDeploymentsCard from "./RecentDeploymentsCard";
import AIAnalysisFeed from "./AIAnalysisFeed";
import NeedsAttention from "./NeedsAttention";
import CommandPalette from "./CommandPalette";
import { OnboardingWizard, OnboardingResumeChip } from "./onboarding";
import DemoBanner from './DemoBanner';
import { usePermissions } from '../utils/permissions';
import { isDemoUser } from '../utils/demo';


const Dashboard = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const isRootDashboard = location.pathname.replace(/\/+$/, "") === "/dash";
  const isSmallScreen = useMediaQuery("(max-width: 860px)");
  const [isSidebarOpen, setIsSidebarOpen] = React.useState(!isSmallScreen);
  const [showOnboarding, setShowOnboarding] = React.useState(true);
  // Setup is for users and admins; a viewer can't change it (the API says 403).
  const canSetUp = usePermissions()("project.write");

  // The composed deployment filter (cluster / region / namespace) is
  // already forwarded on every request by dash.service's withEnv(),
  // which reads it straight from localStorage. What we need it for
  // here is the React Query cache key: without clusterId in the key,
  // switching clusters hits the same cache entry and the dashboard
  // silently keeps showing the previous cluster's numbers.
  const { currentCluster, loading: clustersLoading, filter } = useCluster();
  const clusterId = clustersLoading ? null : (currentCluster?.id ?? null);
  // The environment comes from the top-bar picker (global filter).
  const environment = filter?.environment || 'all';
  // On the Overview, environment and cluster are in the URL too (the
  // pages under /dash/* that filter do their own).
  useFilterUrlSync(isRootDashboard);

  React.useEffect(() => {
    setIsSidebarOpen(!isSmallScreen);
  }, [isSmallScreen]);

  // Every query keys on [name, environment, clusterId] so a change to
  // either filter refetches instead of serving a stale entry.

  // Critical metrics: refresh every 60s
  const {
    data: severityData = [],
    isLoading: loadingSeverity,
    error: errorSeverity
  } = useQuery({
    queryKey: ["issue-stats", "open", environment, clusterId],
    queryFn: () => DashboardService.getIssueStats(environment, "OPEN"),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  // Every open issue, whatever its severity (the statistics above only
  // count critical and warning).
  const { data: openIssues, isLoading: loadingOpen } = useQuery({
    queryKey: ["open-issue-count", environment, clusterId],
    queryFn: () => {
      const params = { status: "OPEN", page_size: 1 };
      if (environment && environment !== "all") params.environment = environment;
      if (clusterId != null) params.cluster = clusterId;
      return dataService.getIssues(params);
    },
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  const { data: healthData, isLoading: loadingHealth } = useQuery({
    queryKey: ["system-health", environment, clusterId],
    queryFn: () => DashboardService.getSystemHealth(environment),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  const { data: trendData, isLoading: loadingTrends } = useQuery({
    queryKey: ["trend-analysis", environment, clusterId],
    queryFn: () => DashboardService.getTrendAnalysis(environment),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  // Slower-changing metrics: refresh every 2 minutes
  const { data: serviceHealthData, isLoading: loadingServiceHealth } = useQuery({
    queryKey: ["service-health-map", environment, clusterId],
    queryFn: () => DashboardService.getServiceHealthMap(7, environment),
    staleTime: 2 * 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
  });

  const { data: rootCauseData, isLoading: loadingRootCause } = useQuery({
    queryKey: ["root-cause-stats", environment, clusterId],
    queryFn: () => DashboardService.getRootCauseStats(30, environment),
    staleTime: 2 * 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
  });

  const { data: deploymentsData, isLoading: loadingDeployments } = useQuery({
    queryKey: ["recent-deployments", environment, clusterId],
    queryFn: () => DashboardService.getRecentDeployments(environment),
    staleTime: 2 * 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
  });

  const { data: analysisFeedData, isLoading: loadingFeed } = useQuery({
    queryKey: ["analysis-feed", environment, clusterId],
    queryFn: () => DashboardService.getAnalysisFeed(5, environment),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  // No empty Recent Deployments panel: the analyses take the width. Hidden
  // for the demo user when there is nothing to list, and when CI/CD is
  // connected but no service has a run yet. A workspace with no CI/CD
  // connected keeps the panel: it carries the hint to add it.
  const deployServices = deploymentsData?.services || [];
  let hasDeployments;
  if (loadingDeployments || deployServices.length === 0) hasDeployments = !isDemoUser();
  else hasDeployments = deployServices.some((s) => s.latest_pipeline);

  const error = errorSeverity ? t('dashboard.errorLoadingStats') : null;

  // Top-row tiles: both count issues that are open now.
  const openCount = openIssues?.pagination?.total_issues ?? openIssues?.results?.length ?? 0;
  const criticalCount = severityData.find(s => (s.name || '').toUpperCase() === "CRITICAL")?.value || 0;

  // Skeleton placeholder for metric cards still loading
  const MetricSkeleton = () => (
    <div className="metric-card skeleton">
      <div className="skeleton-line skeleton-icon" />
      <div className="skeleton-line skeleton-value" />
      <div className="skeleton-line skeleton-label" />
    </div>
  );

  // The skip link moves the focus, not the address (no "#main-content" left
  // in a link someone copies).
  const skipToContent = (e) => {
    e.preventDefault();
    const main = document.getElementById('main-content');
    if (main) main.focus();
  };

  return (
    <div className="dashboard-layout">
      {/* First stop of the Tab key: past the menu and the top bar. */}
      <a href="#main-content" className="ds-skip-link" onClick={skipToContent}>{t('nav.skipToContent')}</a>
      <Sidebar isOpen={isSidebarOpen} setIsOpen={setIsSidebarOpen} />

      <div className={`dashboard-main ${isSidebarOpen ? 'expanded' : 'collapsed'}`}>
        {/* Demo users only: what the demo shows, on every page. */}
        <DemoBanner />

        <Navbar toggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)} />
        <CommandPalette />

        {isRootDashboard && (
          <main className="dashboard-content" id="main-content" tabIndex={-1}>
            <PageHeader
              title={t('nav.overview')}
              subtitle={(
                <span className="d-inline-flex flex-wrap align-items-center gap-2">
                  {t('dashboard.overviewSubtitle')}
                  <span className="live-dot">{t('dashboard.autoRefresh')}</span>
                </span>
              )}
              actions={(
                <Link to="/dash/investigate" className="ds-btn ds-btn-primary">
                  <Search size={16} aria-hidden="true" /> {t('nav.investigate')}
                </Link>
              )}
            />

            {/* What is broken now, why, and what to do — before the numbers. */}
            <NeedsAttention environment={environment} clusterId={clusterId} />

            {/* Key numbers: open critical, open issues, system health.
                Each tile handles its own loading. */}
            <div className="overview-numbers">
              {loadingSeverity ? <MetricSkeleton /> : (
                <Link to="/dash/issues?status=OPEN&severity=Critical" className={`metric-card metric-kpi ${criticalCount > 0 ? 'metric-danger' : 'metric-calm'}`}>
                  <div className="metric-icon" aria-hidden="true"><FaExclamationTriangle /></div>
                  <div className="metric-content">
                    <span className="metric-value">{criticalCount}</span>
                    <span className="metric-label">{t('dashboard.openCritical')}</span>
                  </div>
                  {criticalCount > 0
                    ? <div className="metric-trend negative">{t('dashboard.needsAttention')}</div>
                    : <div className="metric-trend positive">{t('dashboard.allClear')}</div>}
                </Link>
              )}

              {loadingOpen ? <MetricSkeleton /> : (
                <Link to="/dash/issues?status=OPEN" className="metric-card metric-kpi metric-calm">
                  <div className="metric-icon" aria-hidden="true"><FaExclamationCircle /></div>
                  <div className="metric-content">
                    <span className="metric-value">{openCount}</span>
                    <span className="metric-label">{t('dashboard.openIssuesLabel')}</span>
                  </div>
                </Link>
              )}

              <HealthScoreCard score={healthData?.health_score || 0} status={healthData?.status} loading={loadingHealth} />
            </div>

            {error && (
              <div className="error-banner">
                <FaExclamationTriangle />
                <span>{error}</span>
              </div>
            )}

            {/* Latest AI findings beside the latest deploys */}
            <div className="overview-split">
              <div className="overview-main">
                <AIAnalysisFeed data={analysisFeedData} loading={loadingFeed} />
              </div>
              {hasDeployments && (
                <div className="overview-side">
                  <RecentDeploymentsCard data={deploymentsData} loading={loadingDeployments} />
                </div>
              )}
            </div>

            {/* What happened: the 7-day trend beside the causes. */}
            <div className="charts-grid overview-charts">
              <TrendAnalysisChart data={trendData} loading={loadingTrends} />
              <RootCausePie data={rootCauseData} loading={loadingRootCause} />
            </div>

            {/* Where: one panel, the worst service first. Sentinel figures
                are on Settings > Sentinel, correlation insights on Analyses,
                workloads by cluster on Settings > Clusters. */}
            <ServiceHealthHeatmap data={serviceHealthData} loading={loadingServiceHealth} />
          </main>
        )}

        {!isRootDashboard && (
          <main className="dashboard-outlet" id="main-content" tabIndex={-1}>
            <Outlet />
          </main>
        )}
      </div>

      {/* Onboarding wizard — shows for orgs still in setup.
          When the user dismisses, we swap the wizard for a small
          persistent chip (below) so setup isn't silently forgotten. */}
      {canSetUp && showOnboarding && (
        <OnboardingWizard
          onComplete={() => setShowOnboarding(false)}
          onSkip={() => setShowOnboarding(false)}
        />
      )}
      {canSetUp && !showOnboarding && (
        <OnboardingResumeChip onResume={() => setShowOnboarding(true)} />
      )}
    </div>
  );
};


export default Dashboard;

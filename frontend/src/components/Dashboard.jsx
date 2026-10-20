import React from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "./Sidebar";
import Navbar from "./Navbar";
import DashboardService from "../services/dash.service";
import { useCluster } from "../context/ClusterContext";
import { useQuery } from "@tanstack/react-query";
import { FaChartPie, FaExclamationTriangle, FaBolt } from "react-icons/fa";
import { useMediaQuery } from "@mui/material";
import { Search } from "lucide-react";
import PageHeader from "./PageHeader";
import "./Dashboard.css";

import HealthScoreCard from "./HealthScoreCard";
import ServiceRankingChart from "./ServiceRankingChart";
import TrendAnalysisChart from "./TrendAnalysisChart";
import MTTRCard from "./MTTRCard";
import RootCausePie from "./RootCausePie";
import ServiceHealthHeatmap from "./ServiceHealthHeatmap";
import RecentDeploymentsCard from "./RecentDeploymentsCard";
import WorkloadsByCluster from "./WorkloadsByCluster";
import CorrelationInsightsCard from "./CorrelationInsightsCard";
import AIAnalysisFeed from "./AIAnalysisFeed";
import SentinelStatsCard from "./SentinelStatsCard";
import NeedsAttention from "./NeedsAttention";
import CommandPalette from "./CommandPalette";
import { OnboardingWizard, OnboardingResumeChip } from "./onboarding";
import { isDemoUser } from '../utils/demo';
import { usePermissions } from '../utils/permissions';


const Dashboard = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const isRootDashboard = location.pathname === "/dash";
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

  React.useEffect(() => {
    setIsSidebarOpen(!isSmallScreen);
  }, [isSmallScreen]);

  // Every query keys on [name, environment, clusterId] so a change to
  // either filter refetches instead of serving a stale entry.

  // Critical metrics: refresh every 60s
  const {
    data: chartData = [],
    isLoading: loadingRecs,
    error: errorRecs
  } = useQuery({
    queryKey: ["recommendation-stats", environment, clusterId],
    queryFn: () => DashboardService.getRecommendationStats(environment),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  const {
    data: severityData = [],
    isLoading: loadingSeverity,
    error: errorSeverity
  } = useQuery({
    queryKey: ["issue-stats", environment, clusterId],
    queryFn: async () => {
      const severityStats = await DashboardService.getIssueStats(environment);
      return severityStats.filter(entry =>
        entry.name.toUpperCase() === "CRITICAL" ||
        entry.name.toUpperCase() === "WARNING"
      );
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

  const { data: serviceRanking, isLoading: loadingServices } = useQuery({
    queryKey: ["service-reliability", environment, clusterId],
    queryFn: () => DashboardService.getServiceReliability(environment),
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
  const { data: mttrData, isLoading: loadingMTTR } = useQuery({
    queryKey: ["mttr-stats", environment, clusterId],
    queryFn: () => DashboardService.getMTTRStats(30, environment),
    staleTime: 2 * 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
  });

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

  // New widgets
  const { data: correlationData, isLoading: loadingCorrelations } = useQuery({
    queryKey: ["correlation-insights", environment, clusterId],
    queryFn: () => DashboardService.getCorrelationInsights(7, environment),
    staleTime: 2 * 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
  });

  const { data: analysisFeedData, isLoading: loadingFeed } = useQuery({
    queryKey: ["analysis-feed", environment, clusterId],
    queryFn: () => DashboardService.getAnalysisFeed(5, environment),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  const { data: sentinelData, isLoading: loadingSentinel } = useQuery({
    queryKey: ["sentinel-stats", environment, clusterId],
    queryFn: () => DashboardService.getSentinelStats(7, environment),
    staleTime: 2 * 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
  });

  const error = errorRecs || errorSeverity ? t('dashboard.errorLoadingStats') : null;

  // Calculate totals for top-row cards
  const totalRecommendations = chartData.reduce((sum, item) => sum + item.value, 0);
  const criticalCount = severityData.find(s => s.name === "CRITICAL")?.value || 0;

  // Skeleton placeholder for metric cards still loading
  const MetricSkeleton = () => (
    <div className="metric-card skeleton">
      <div className="skeleton-line skeleton-icon" />
      <div className="skeleton-line skeleton-value" />
      <div className="skeleton-line skeleton-label" />
    </div>
  );

  // Read the persistent demo flag from the login payload so we can
  // surface the "you're in the live demo" banner on every page. We
  // intentionally trust localStorage here rather than fetching /me on
  // every render — Knox + RBAC will reject any write the banner says
  // is blocked, so the flag is presentational, not security-bearing.
  const isDemo = isDemoUser();

  return (
    <div className="dashboard-layout">
      <Sidebar isOpen={isSidebarOpen} setIsOpen={setIsSidebarOpen} />

      <div className={`dashboard-main ${isSidebarOpen ? 'expanded' : 'collapsed'}`}>
        {isDemo && (
          <div className="demo-banner" role="status">
            <span>
              You're in the SerOps live demo · seeded data · resets nightly · nothing hits live infra.
            </span>
            <a
              href="https://serops.ai/docs/getting-started/quick-start-self-hosted/"
              target="_blank"
              rel="noopener noreferrer"
            >
              Self-host SerOps →
            </a>
          </div>
        )}

        <Navbar toggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)} />
        <CommandPalette />

        {isRootDashboard && (
          <div className="dashboard-content">
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

            {/* Key numbers — each card handles its own loading */}
            <div className="overview-numbers">
              <HealthScoreCard score={healthData?.health_score || 0} status={healthData?.status} loading={loadingHealth} />
              <MTTRCard data={mttrData} loading={loadingMTTR} />

              {loadingRecs ? <MetricSkeleton /> : (
                <div className="metric-card metric-primary">
                  <div className="metric-icon"><FaBolt /></div>
                  <div className="metric-content">
                    <span className="metric-value">{totalRecommendations}</span>
                    <span className="metric-label">{t('dashboard.aiInsights')}</span>
                  </div>
                  <div className="metric-trend positive"><FaChartPie /> {t('dashboard.active')}</div>
                </div>
              )}

              {loadingSeverity ? <MetricSkeleton /> : (
                <div className="metric-card metric-danger">
                  <div className="metric-icon"><FaExclamationTriangle /></div>
                  <div className="metric-content">
                    <span className="metric-value">{criticalCount}</span>
                    <span className="metric-label">{t('issues.critical')}</span>
                  </div>
                  {criticalCount > 0
                    ? <div className="metric-trend negative">{t('dashboard.needsAttention')}</div>
                    : <div className="metric-trend positive">{t('dashboard.allClear')}</div>}
                </div>
              )}
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
              <div className="overview-side">
                <RecentDeploymentsCard data={deploymentsData} loading={loadingDeployments} />
              </div>
            </div>

            <h2 className="overview-section-title">{t('dashboard.trendsTitle')}</h2>
            <div className="charts-grid overview-charts">
              {/* Pairs, so no card sits alone in a half-empty row:
                  what happened (trend, causes), where (services), and
                  how SerOps helped (correlations, Sentinel). */}
              <TrendAnalysisChart data={trendData} loading={loadingTrends} />
              <RootCausePie data={rootCauseData} loading={loadingRootCause} />
              <ServiceRankingChart data={serviceRanking} loading={loadingServices} />
              <ServiceHealthHeatmap data={serviceHealthData} loading={loadingServiceHealth} />
              <CorrelationInsightsCard data={correlationData} loading={loadingCorrelations} />
              <SentinelStatsCard data={sentinelData} loading={loadingSentinel} />
            </div>

            {/* Multi-cluster orgs get a per-cluster workload breakdown
                (Item #19). Renders nothing when the org has 0-1 clusters. */}
            <WorkloadsByCluster />
          </div>
        )}

        {!isRootDashboard && (
          <div className="dashboard-outlet">
            <Outlet />
          </div>
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

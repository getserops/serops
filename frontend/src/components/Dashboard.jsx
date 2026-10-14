import React from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "./Sidebar";
import Navbar from "./Navbar";
import DashboardService from "../services/dash.service";
import { useCluster } from "../context/ClusterContext";
import { useQuery } from "@tanstack/react-query";
import { FaChartPie, FaExclamationTriangle, FaBolt } from "react-icons/fa";
import { useMediaQuery } from "@mui/material";
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
import { OnboardingWizard, OnboardingResumeChip } from "./onboarding";
import { isDemoUser } from '../utils/demo';


const ENV_OPTIONS = ['all', 'production', 'staging', 'dev'];

const Dashboard = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const isRootDashboard = location.pathname === "/dash";
  const isSmallScreen = useMediaQuery("(max-width: 860px)");
  const [isSidebarOpen, setIsSidebarOpen] = React.useState(!isSmallScreen);
  const [showOnboarding, setShowOnboarding] = React.useState(true);
  const [environment, setEnvironment] = React.useState('all');

  // The composed deployment filter (cluster / region / namespace) is
  // already forwarded on every request by dash.service's withEnv(),
  // which reads it straight from localStorage. What we need it for
  // here is the React Query cache key: without clusterId in the key,
  // switching clusters hits the same cache entry and the dashboard
  // silently keeps showing the previous cluster's numbers.
  const { currentCluster, loading: clustersLoading } = useCluster();
  const clusterId = clustersLoading ? null : (currentCluster?.id ?? null);

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
          <div
            className="demo-banner"
            role="status"
            style={{
              background: '#fef3c7',
              color: '#92400e',
              padding: '0.5rem 1rem',
              fontSize: '0.875rem',
              fontWeight: 500,
              borderBottom: '1px solid #fde68a',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '0.5rem',
            }}
          >
            <span>
              You're in the SerOps live demo · seeded data · resets nightly · nothing hits live infra.
            </span>
            <a
              href="https://serops.ai/docs/getting-started/quick-start-self-hosted/"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: '#92400e',
                textDecoration: 'underline',
                fontWeight: 600,
              }}
            >
              Self-host SerOps →
            </a>
          </div>
        )}

        <Navbar toggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)} />

        {isRootDashboard && (
          <div className="dashboard-content">
            {/* Header with environment filter */}
            <div className="dashboard-header">
              <div className="header-text">
                <h1>{t('dashboard.systemHealth')}</h1>
                <p>{t('dashboard.realTimeMonitoring')}</p>
              </div>
              <div className="env-filter">
                {ENV_OPTIONS.map(env => (
                  <button
                    key={env}
                    className={`env-filter-btn ${environment === env ? 'active' : ''}`}
                    onClick={() => setEnvironment(env)}
                  >
                    {env === 'all' ? t('dashboard.envAll', 'All') : env.charAt(0).toUpperCase() + env.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            {/* Row 1: Health & Metrics — 4 cards, each handles its own loading */}
            <div className="metrics-grid">
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

            {/* Row 2: AI Intelligence — full-width analysis feed */}
            <AIAnalysisFeed data={analysisFeedData} loading={loadingFeed} />

            <hr className="section-divider" />

            {/* Row 3: Charts Grid */}
            <div className="charts-grid extended-grid">
              <TrendAnalysisChart data={trendData} loading={loadingTrends} />
              <ServiceRankingChart data={serviceRanking} loading={loadingServices} />
              <ServiceHealthHeatmap data={serviceHealthData} loading={loadingServiceHealth} />
              <CorrelationInsightsCard data={correlationData} loading={loadingCorrelations} />
              <SentinelStatsCard data={sentinelData} loading={loadingSentinel} />
              <RootCausePie data={rootCauseData} loading={loadingRootCause} />
              <RecentDeploymentsCard data={deploymentsData} loading={loadingDeployments} />
            </div>

            {/* Multi-cluster orgs get a per-cluster workload breakdown
                (Item #19). Renders nothing when the org has 0-1 clusters. */}
            <WorkloadsByCluster />
          </div>
        )}

        <div className="dashboard-outlet">
          <Outlet />
        </div>
      </div>

      {/* Onboarding wizard — shows for orgs still in setup.
          When the user dismisses, we swap the wizard for a small
          persistent chip (below) so setup isn't silently forgotten. */}
      {showOnboarding && (
        <OnboardingWizard
          onComplete={() => setShowOnboarding(false)}
          onSkip={() => setShowOnboarding(false)}
        />
      )}
      {!showOnboarding && (
        <OnboardingResumeChip onResume={() => setShowOnboarding(true)} />
      )}
    </div>
  );
};


export default Dashboard;

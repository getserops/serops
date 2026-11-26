import React from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "./Sidebar";
import Navbar from "./Navbar";
import DashboardService from "../services/dash.service";
import { useCluster } from "../context/ClusterContext";
import useFilterUrlSync from "../hooks/useFilterUrlSync";
import { useQuery } from "@tanstack/react-query";
import { useMediaQuery } from "@mui/material";
import { Search } from "lucide-react";
import PageHeader from "./PageHeader";
import "./Dashboard.css";

import TrendAnalysisChart from "./TrendAnalysisChart";
import StatusCard from "./overview/StatusCard";
import ServicesPanel from "./overview/ServicesPanel";
import CausesBar from "./overview/CausesBar";
import RecentDeploymentsCard from "./RecentDeploymentsCard";
import AIAnalysisFeed from "./AIAnalysisFeed";
import NeedsAttention from "./NeedsAttention";
import CommandPalette from "./CommandPalette";
import { OnboardingWizard, OnboardingResumeChip } from "./onboarding";
import DemoBanner from './DemoBanner';
import PhoneCollapse from './PhoneCollapse';
import { usePermissions } from '../utils/permissions';
import { isDemoUser } from '../utils/demo';


const Dashboard = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const isRootDashboard = location.pathname.replace(/\/+$/, "") === "/dash";
  const isSmallScreen = useMediaQuery("(max-width: 860px)");
  // Phone: the panels under the analyses are reduced to their header.
  const isPhone = useMediaQuery("(max-width: 767px)");
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

            {/* 1.5.6, top to bottom: the status of every service, the open
                issues, the services by name beside the latest analyses,
                then the week. */}
            <StatusCard data={serviceHealthData} loading={loadingServiceHealth} />

            <NeedsAttention environment={environment} clusterId={clusterId} />

            {/* On a phone the panels below "Needs attention now" are
                reduced to their header, as in 1.5.5. */}
            <div className="glance-cols">
              <PhoneCollapse phone={isPhone} title={t('dashboard.glance.services')}>
                <ServicesPanel data={serviceHealthData} loading={loadingServiceHealth} />
              </PhoneCollapse>
              <PhoneCollapse phone={isPhone} title={t('dashboard.glance.recentAnalyses')}>
                <AIAnalysisFeed data={analysisFeedData} loading={loadingFeed} />
              </PhoneCollapse>
            </div>

            {hasDeployments && (
              <div className="glance-deployments">
                <PhoneCollapse phone={isPhone} title={t('dashboard.recentDeployments')}>
                  <RecentDeploymentsCard data={deploymentsData} loading={loadingDeployments} />
                </PhoneCollapse>
              </div>
            )}

            <div className="glance-week">
              <PhoneCollapse phone={isPhone} title={t('dashboard.glance.weekIssues')}>
                <TrendAnalysisChart data={trendData} loading={loadingTrends} />
              </PhoneCollapse>
              <PhoneCollapse phone={isPhone} title={t('dashboard.glance.weekCauses')}>
                <CausesBar data={rootCauseData} loading={loadingRootCause} />
              </PhoneCollapse>
            </div>
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

import React, { Suspense, lazy, useEffect } from "react";
import "./App.css";
import "./styles/primitives.css";
import {
  BrowserRouter as Router,
  Route,
  Routes,
  Navigate,
} from "react-router-dom";
import { ClusterProvider } from "./context/ClusterContext";
import ErrorBoundary from "./components/ErrorBoundary";

// Lazy loading components
// Public registration now ENABLED for SaaS
const Register = lazy(() => import("./components/Register"));
const RegisterPart3 = lazy(() => import("./components/RegisterPart3"));
const Invitation = lazy(() => import("./components/Invitation"));
const Password = lazy(() => import("./components/Password"));
const PasswordReset = lazy(() => import("./components/PasswordReset"));
const Login = lazy(() => import("./components/Login"));
const SSOCallback = lazy(() => import("./components/SSOCallback"));
const Dashboard = lazy(() => import("./components/Dashboard"));
const Profile = lazy(() => import("./pages/Profile"));
const Data = lazy(() => import("./components/Data"));
const Details = lazy(() => import("./components/Detail"));
const Metrics = lazy(() => import("./components/Metrics"));
const CodeChanges = lazy(() => import("./components/CodeChanges"));
// Errors page removed — was a non-functional mock with hardcoded data
const Issues = lazy(() => import("./components/Issues"));
const ChatIssues = lazy(() => import("./components/ChatIssues"));
const Traces = lazy(() => import("./components/Traces"));
const TraceDetail = lazy(() => import("./components/TraceDetail"));
const BatchTraces = lazy(() => import("./components/BatchTraces"));
const BatchTimeline = lazy(() => import("./components/BatchTimeline"));
const Project = lazy(() => import("./components/Project"));
const ServiceProjects = lazy(() => import("./components/serviceProjects"));
const NotificationPanel = lazy(() => import("./components/NotificationPanel"));

// Settings components (new)
const SettingsLayout = lazy(() => import("./components/settings/SettingsLayout"));
const GeneralSettings = lazy(() => import("./components/settings/GeneralSettings"));
const TeamSettings = lazy(() => import("./components/settings/TeamSettings"));
// PR-N phase 2 (2026-09-26): NotificationSettings retired.
// Delivery Channels (was incident-channels) + Routing Rules replace it.
const RoutingRulesSettings = lazy(() => import("./components/settings/RoutingRulesSettings"));
const AISettings = lazy(() => import("./components/settings/AISettings"));
const DataSettings = lazy(() => import("./components/settings/DataSettings"));
const SecuritySettings = lazy(() => import("./components/settings/SecuritySettings"));
const AuditLogSettings = lazy(() => import("./components/settings/AuditLogSettings"));
const SentinelSettings = lazy(() => import("./components/settings/SentinelSettings"));
const SettingsIntegrations = lazy(() => import("./components/SettingsIntegrations"));
const TracesSettings = lazy(() => import("./components/settings/TracesSettings"));
const ClusterSettings = lazy(() => import("./components/settings/ClusterSettings"));
const IncidentChannelsSettings = lazy(() => import("./components/settings/IncidentChannelsSettings"));
const UserPreferencesSettings = lazy(() => import("./components/settings/UserPreferencesSettings"));

// Loading fallback component
const PageLoader = () => (
  <div className="d-flex justify-content-center align-items-center" style={{ height: '100vh' }}>
    <div className="spinner-border text-primary" role="status">
      <span className="visually-hidden">Loading...</span>
    </div>
  </div>
);

// Apply theme on load
const applyTheme = (theme) => {
  if (theme === 'system') {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
  } else {
    document.documentElement.setAttribute('data-theme', theme);
  }
};

function App() {
  // Apply saved theme on app load
  useEffect(() => {
    const savedSettings = JSON.parse(localStorage.getItem('seropsSettings') || '{}');
    const theme = savedSettings.theme || 'system';
    applyTheme(theme);

    // Listen for system theme changes if using system preference
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = () => {
      const currentSettings = JSON.parse(localStorage.getItem('seropsSettings') || '{}');
      if (currentSettings.theme === 'system') {
        applyTheme('system');
      }
    };
    mediaQuery.addEventListener('change', handleChange);

    // Listen for settings changes from GeneralSettings
    const handleSettingsChange = (e) => {
      if (e.detail?.theme) {
        applyTheme(e.detail.theme);
      }
    };
    window.addEventListener('settingsChanged', handleSettingsChange);

    return () => {
      mediaQuery.removeEventListener('change', handleChange);
      window.removeEventListener('settingsChanged', handleSettingsChange);
    };
  }, []);

  return (
    <div className="App">
      <Router>
        <ClusterProvider>
        <ErrorBoundary>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            {/* Authentication routes */}
            {/* Public registration ENABLED */}
            <Route path="/register" element={<Register />} />
            <Route path="/register_verif" element={<RegisterPart3 />} />
            <Route path="/accept_invitation/:string" element={<Invitation />} />
            <Route path="/invitation_password" element={<Password />} />
            <Route
              path="/password/reset/:uid/:token"
              element={<PasswordReset />}
            />
            <Route path="/login" element={<Login />} />
            <Route path="/auth/callback" element={<SSOCallback />} />
            <Route path="/dash" element={<Dashboard />} />
            <Route path="/notifications" element={<NotificationPanel />} />

            {/* Dashboard routes */}
            <Route path="/dash/*" element={<Dashboard />}>
              <Route path="profile" element={<Profile />} />
              <Route path="data" element={<Data />}>
                <Route path="details/:batchId" element={<Details />} />
              </Route>
              <Route path="metrics/:batchId" element={<Metrics />} />
              <Route path="code-changes/:batchId" element={<CodeChanges />} />
              <Route path="errors" element={<Navigate to="/dash/issues" replace />} />
              <Route path="issues" element={<Issues />} />
              <Route path="issues/:batchId" element={<Issues />} />
              <Route path="chat" element={<ChatIssues />} />
              <Route path="traces" element={<Traces />} />
              <Route path="traces/batch/:batchId" element={<BatchTraces />} />
              <Route path="traces/:traceId" element={<TraceDetail />} />
              <Route path="timeline/:batchId" element={<BatchTimeline />} />

              {/* Projects */}
              <Route path="projects" element={<Project />} />
              <Route path="projects/:projectId" element={<ServiceProjects />} />

              {/* Settings with sidebar layout */}
              <Route path="settings" element={<SettingsLayout />}>
                <Route index element={<GeneralSettings />} />
                <Route path="team" element={<TeamSettings />} />
                {/* PR-N phase 2 (2026-09-26): Delivery Channels + Routing Rules
                    replace the old notification-settings page. Legacy
                    /settings/notifications and /settings/incident-channels
                    now redirect to /settings/delivery. */}
                <Route path="delivery" element={<IncidentChannelsSettings />} />
                <Route path="routing-rules" element={<RoutingRulesSettings />} />
                <Route path="notifications" element={<Navigate to="/dash/settings/delivery" replace />} />
                <Route path="incident-channels" element={<Navigate to="/dash/settings/delivery" replace />} />
                <Route path="preferences" element={<UserPreferencesSettings />} />
                <Route path="ai" element={<AISettings />} />
                <Route path="sentinel" element={<SentinelSettings />} />
                <Route path="data" element={<DataSettings />} />
                <Route path="security" element={<SecuritySettings />} />
                <Route path="audit" element={<AuditLogSettings />} />
                <Route path="integrations" element={<SettingsIntegrations />} />
                <Route path="traces" element={<TracesSettings />} />
                <Route path="clusters" element={<ClusterSettings />} />
              </Route>
            </Route>

            {/* Default redirect to login */}
            <Route path="/" element={<Navigate to="/login" />} />
          </Routes>
        </Suspense>
        </ErrorBoundary>
        </ClusterProvider>
      </Router>
    </div>
  );
}

export default App;

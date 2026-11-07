import React from 'react';
import ReactDOM from 'react-dom/client';
// Fonts ship with the app: loading them from Google Fonts sent every
// visitor's browser to Google, broke them on air-gapped installs, and is
// blocked by the Content-Security-Policy (style and font from SerOps only).
import '@fontsource/inter/300.css';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import './index.css';
import 'bootstrap/dist/css/bootstrap.min.css';
import App from './App';
import reportWebVitals from './reportWebVitals';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

// Initialize internationalization
import './i18n';
import { installReadOnlyDemoHandling } from './utils/readOnlyDemo';
import { installCollapsibleToggle } from './utils/textFormatters';
import { installStackTables } from './utils/stackTables';
import { installStaleBuildReload } from './utils/staleBuild';

installReadOnlyDemoHandling();
installCollapsibleToggle();
installStackTables();
installStaleBuildReload();

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60 * 1000, // 5 minutes
    },
  },
});

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <ToastContainer
        position="top-right"
        autoClose={3000}
        hideProgressBar={false}
        newestOnTop
        closeOnClick
        pauseOnHover
      />
    </QueryClientProvider>
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();

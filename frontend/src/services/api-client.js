import axios from "axios";

const AUTH_HOST = import.meta.env.VITE_BASE_URL;

// Public routes that must never bounce to /login on a 401 — the user
// hasn't logged in yet (that's the whole point of the page). Without
// this whitelist, background API calls fired while these pages mount
// hijack the navigation and strand the user back on /login (E34-1).
const PUBLIC_AUTH_PATHS = [
    "/login",
    "/register",
    "/register_verif",
    "/accept_invitation",   // /accept_invitation/:token
    "/invitation_password",
    "/password/reset",      // /password/reset/:uid/:token
    "/auth/callback",       // SSO callback
];

function isPublicAuthPath(pathname) {
    return PUBLIC_AUTH_PATHS.some((p) => pathname.startsWith(p));
}

const apiClient = axios.create({
    baseURL: AUTH_HOST,
    headers: {
        "Content-Type": "application/json",
    },
});

// Request interceptor for API calls
apiClient.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem("token");
        if (token) {
            config.headers["Authorization"] = `Token ${token}`;
        }
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

// Response interceptor for API calls
apiClient.interceptors.response.use(
    (response) => {
        return response;
    },
    async (error) => {
        const originalRequest = error.config;

        // Handle 401 Unauthorized
        if (error.response && error.response.status === 401) {
            // Clear local storage
            localStorage.removeItem("token");
            localStorage.removeItem("user");

            // Redirect to login unless we're already on a public auth
            // page (login, register, reset, accept-invitation, SSO
            // callback). Redirecting from those hijacks the user's
            // in-progress flow.
            if (!isPublicAuthPath(window.location.pathname)) {
                window.location.href = "/login";
            }
            return Promise.reject(error);
        }

        // Pass other errors through
        return Promise.reject(error);
    }
);

export default apiClient;

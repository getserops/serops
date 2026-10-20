import axios from "axios";

const AUTH_HOST = import.meta.env.VITE_BASE_URL;
const AuthService = {};

AuthService.login = (email, password) => {
  return axios.post(AUTH_HOST + "/auth/login", {
    email: email,
    password: password,
  });
};

AuthService.register = (data) => {
  return axios.post(AUTH_HOST + "/auth/register", data);
};

AuthService.verify = (token) => {
  return axios.get(AUTH_HOST + "/auth/activate/", token);
};
AuthService.accept_invitation = (string) => {
  return axios.get(AUTH_HOST + "/auth/accept/invitation/" + string);
};
AuthService.password_invitation = (data) => {
  return axios.post(AUTH_HOST + "/auth/accept/password", data);
};
AuthService.password_forget = (email) => {
  return axios.post(AUTH_HOST + "/auth/password/forget", { email: email });
};
AuthService.password_set = (uid, token, data) => {
  return axios.post(`${AUTH_HOST}/auth/password/set/${uid}/${token}`, data);
};
AuthService.logout = async () => {
  try {
    const token = localStorage.getItem("token");

    const response = await axios.post(
      AUTH_HOST + "/auth/logout",
      {},
      {
        headers: {
          Authorization: `Token ${token}`,
        },
      }
    );
    // Handle successful logout here (optional)
    return response;
  } catch (error) {
    console.error("Logout error:", error);
    // Handle logout error gracefully (e.g., notify user)
  }
};

AuthService.getUser = () => {
  let user = localStorage.getItem("user");
  if (user) {
    return JSON.parse(user);
  } else {
    return null;
  }
};
AuthService.setUser = (data) => {
  let user = localStorage.setItem("user", data);
  if (user) {
    return JSON.parse(user);
  } else {
    return null;
  }
};
AuthService.authHeader = () => {
  let token = localStorage.getItem("token");
  if (token) {
    return {
      headers: {
        Authorization: "Token " + token,
      },
    };
  } else {
    window.location.href = "/login";
  }
};

AuthService.update = (user) => {
  return axios.put(
    AUTH_HOST + "/users/" + user._id,
    user,
    AuthService.authHeader()
  );
};
AuthService.getOne = (id) => {
  return axios.get(AUTH_HOST + "/users/" + id, AuthService.authHeader());
};
AuthService.resendVerify = () => {
  return axios.get(AUTH_HOST + "auth/resend");
};

AuthService.forgetPassword = (email) => {
  return axios.get(AUTH_HOST + "/reset/users/" + email);
};

AuthService.resetPassword = (data) => {
  return axios.post(AUTH_HOST + "/auth/password", data);
};

/**
 * Exchange the short-lived SSO handoff cookie for a usable Knox token.
 * The browser sends the HttpOnly cookie automatically; we need
 * withCredentials so axios includes it on this cross-origin POST.
 */
AuthService.ssoExchange = () => {
  return axios.post(AUTH_HOST + "/auth/sso/exchange", {}, { withCredentials: true });
};

/**
 * One-click bootstrap for the public read-only demo. Returns a Knox
 * token + the demo user payload. Caller is expected
 * to mirror the regular login flow (persist token + user, redirect to
 * /dash).
 */
// `source` (optional, e.g. "landing") is sent as ?src= so the server's
// access log can tell where demo visitors came from. The API ignores it.
AuthService.demoLogin = (source) => {
  const src = source && /^[a-z0-9-]{1,32}$/i.test(source) ? `?src=${source}` : "";
  return axios.post(AUTH_HOST + "/auth/demo-login" + src);
};

/**
 * Public flag the Login page reads at mount so it can hide the
 * "Create account" prompt on deployments that disable open
 * registration (e.g. the public demo host). Always safe to call
 * anonymously; older backends without this endpoint return 404 and
 * the caller keeps the default (registration enabled).
 */
AuthService.registrationStatus = () => {
  return axios.get(AUTH_HOST + "/auth/registration-status");
};

export default AuthService;

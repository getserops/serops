import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AuthService from "../services/auth.service";

/**
 * Landing page that the backend redirects to after a successful SSO
 * authentication. The backend has placed the auth token in a HttpOnly
 * cookie scoped to /api/auth/sso/exchange — we POST there once to
 * exchange the cookie for a usable token, which we then store in
 * localStorage (matching the regular login flow).
 */
const SSOCallback = () => {
  const navigate = useNavigate();
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const exchange = async () => {
      try {
        const response = await AuthService.ssoExchange();
        if (cancelled) return;

        const { token, user } = response.data;
        if (!token) {
          setError("SSO exchange returned no token.");
          return;
        }

        localStorage.setItem("token", token);
        localStorage.setItem("user", JSON.stringify(user));
        navigate("/dash", { replace: true });
      } catch (err) {
        if (cancelled) return;
        const msg =
          err.response?.data?.error ||
          "SSO sign-in could not be completed. Please try again.";
        setError(msg);
      }
    };

    exchange();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  if (error) {
    return (
      <div className="d-flex flex-column align-items-center justify-content-center" style={{ height: "100vh" }}>
        <h4 className="mb-3">SSO sign-in failed</h4>
        <p className="text-muted">{error}</p>
        <button className="btn btn-primary mt-3" onClick={() => navigate("/login")}>
          Back to login
        </button>
      </div>
    );
  }

  return (
    <div className="d-flex justify-content-center align-items-center" style={{ height: "100vh" }}>
      <div className="spinner-border text-primary" role="status">
        <span className="visually-hidden">Completing SSO sign-in…</span>
      </div>
    </div>
  );
};

export default SSOCallback;

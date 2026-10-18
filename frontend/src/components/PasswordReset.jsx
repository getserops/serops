import React, { useState, useMemo } from "react";
import "./Login.css";
import { useNavigate, useParams } from "react-router-dom";
import { FaCheck, FaTimes, FaSpinner, FaLock } from "react-icons/fa";
import AuthService from "../services/auth.service";
import BrandMark from './BrandMark';

const MIN_PASSWORD_LENGTH = 8;

const PasswordReset = () => {
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const { uid, token } = useParams();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const navigate = useNavigate();

  const validation = useMemo(() => {
    const hasMinLength = password.length >= MIN_PASSWORD_LENGTH;
    const passwordsMatch = password === passwordConfirmation && password !== "";
    const isValid = hasMinLength && passwordsMatch;
    return { hasMinLength, passwordsMatch, isValid };
  }, [password, passwordConfirmation]);

  const getPasswordStrength = () => {
    if (password.length === 0) return { level: 0, label: "", color: "" };
    if (password.length < 8)  return { level: 1, label: "Weak",   color: "var(--danger-500)" };
    if (password.length < 12) return { level: 2, label: "Fair",   color: "var(--warning-500)" };
    if (password.length < 16) return { level: 3, label: "Good",   color: "var(--success-500)" };
    return { level: 4, label: "Strong", color: "var(--success-600)" };
  };
  const strength = getPasswordStrength();

  const submit = (e) => {
    e.preventDefault();
    if (!validation.isValid) {
      setError("Please meet all password requirements");
      return;
    }
    setLoading(true);
    setError("");
    AuthService.password_set(uid, token, {
      new_password: password,
      new_password_confirm: passwordConfirmation,
    })
      .then(() => {
        setError("");
        setSuccess(true);
        setTimeout(() => navigate("/login"), 2000);
      })
      .catch((err) => {
        setError(err?.response?.data?.message || "Failed to set password. Please try again.");
        setLoading(false);
      });
  };

  const Requirement = ({ met, text }) => (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.85rem" }}>
      {met
        ? <FaCheck style={{ color: "var(--success-500)" }} />
        : <FaTimes style={{ color: "var(--danger-500)" }} />}
      <span style={{ color: met ? "var(--success-600)" : "var(--text-tertiary)" }}>{text}</span>
    </div>
  );

  return (
    <div className="login-page">
      <div className="login-form-panel">
        <div className="form-container">
          <div className="form-header">
            <BrandMark className="form-logo" />
            <h2>Set your password</h2>
            <p>Create a secure password for your account.</p>
          </div>

          <form onSubmit={submit} className="login-form">
            <div className="form-group">
              <label htmlFor="password">New password</label>
              <div className="input-wrapper">
                <FaLock className="input-icon" />
                <input
                  type="password"
                  id="password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
            </div>

            {/* Requirements + strength meter */}
            <div style={{
              padding: "0.75rem 0.875rem",
              background: "var(--bg-sunken)",
              border: "1px solid var(--border-default)",
              borderRadius: "6px",
              display: "flex",
              flexDirection: "column",
              gap: "0.5rem",
            }}>
              <div style={{ fontSize: "0.8rem", fontWeight: 500, color: "var(--text-secondary)" }}>
                Password requirements
              </div>
              <Requirement met={validation.hasMinLength} text={`At least ${MIN_PASSWORD_LENGTH} characters`} />
              {password.length > 0 && (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: "0.25rem" }}>
                  <div style={{
                    flex: 1, height: "4px",
                    background: "var(--border-default)",
                    borderRadius: "999px", overflow: "hidden"
                  }}>
                    <div style={{
                      width: `${strength.level * 25}%`, height: "100%",
                      background: strength.color, transition: "width 0.3s ease"
                    }} />
                  </div>
                  <span style={{ fontSize: "0.75rem", fontWeight: 500, color: strength.color }}>
                    {strength.label}
                  </span>
                </div>
              )}
            </div>

            <div className="form-group">
              <label htmlFor="password_confirmation">Confirm password</label>
              <div className="input-wrapper">
                <FaLock className="input-icon" />
                <input
                  type="password"
                  id="password_confirmation"
                  placeholder="Rewrite your password"
                  value={passwordConfirmation}
                  onChange={(e) => setPasswordConfirmation(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              {passwordConfirmation.length > 0 && (
                <div style={{ marginTop: "0.375rem" }}>
                  <Requirement met={validation.passwordsMatch} text="Passwords match" />
                </div>
              )}
            </div>

            {error && <div className="alert-error"><span>{error}</span></div>}
            {success && (
              <div className="alert-success">
                <span>Your password has been set. Redirecting to sign in…</span>
              </div>
            )}

            <button
              type="submit"
              className="submit-btn"
              disabled={loading || !validation.isValid}
            >
              {loading
                ? <><FaSpinner className="spin" style={{ marginRight: "0.5rem" }} /> Setting password…</>
                : "Set password"}
            </button>
          </form>
        </div>

        <div className="login-footer">
          <span>&copy; {new Date().getFullYear()} SerOps. All rights reserved.</span>
        </div>
      </div>
    </div>
  );
};

export default PasswordReset;

import React, { useState } from "react";
import "./Login.css";
import { useNavigate } from "react-router-dom";
import { FaLock } from "react-icons/fa";
import AuthService from "../services/auth.service";
import { describeRequestError } from "../utils/apiError";
import BrandMark from './BrandMark';
import { useTranslation } from "react-i18next";

const Password = () => {
  const { t } = useTranslation();
  const [password_confirmation, setPassword_confirmation] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const navigate = useNavigate();

  // Read the invitation JWT stashed by Invitation.jsx after it
  // validated the invite link. Backend derives user_id from the
  // signed token — the prior localStorage('id') pattern let the
  // client claim any user_id, which was an account-takeover
  // vector fixed 2026-08-30. sessionStorage clears on tab close.
  const invitationToken = sessionStorage.getItem('invitation_token') || '';

  const submit = (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    if (!invitationToken) {
      setError(t("passwordPages.linkExpired"));
      setLoading(false);
      return;
    }

    AuthService.password_invitation({
      token: invitationToken,
      password,
      password_confirmation,
    })
      .then(() => {
        setError("");
        setSuccess(true);
        // Token is single-use — clear it so the browser doesn't
        // hold a reusable credential after we're done.
        sessionStorage.removeItem('invitation_token');
        setTimeout(() => navigate("/login"), 2000);
      })
      .catch((err) => {
        setError(describeRequestError(err, t("passwordPages.wrongPassword")));
        setLoading(false);
      });
  };

  return (
    <div className="login-page">
      <div className="login-form-panel">
        <div className="form-container">
          <div className="form-header">
            <BrandMark className="form-logo" />
            <h2>{t("passwordPages.title")}</h2>
            <p>{t("passwordPages.subtitle")}</p>
          </div>

          <form onSubmit={submit} className="login-form">
            <div className="form-group">
              <label htmlFor="password">{t("auth.password")}</label>
              <div className="input-wrapper">
                <FaLock className="input-icon" />
                <input
                  type="password"
                  id="password"
                  placeholder={t("login.passwordPlaceholder")}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="password_confirmation">{t("passwordPages.confirm")}</label>
              <div className="input-wrapper">
                <FaLock className="input-icon" />
                <input
                  type="password"
                  id="password_confirmation"
                  placeholder={t("passwordPages.rewrite")}
                  value={password_confirmation}
                  onChange={(e) => setPassword_confirmation(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
            </div>

            {error && <div className="alert-error"><span>{error}</span></div>}
            {success && (
              <div className="alert-success">
                <span>{t("passwordPages.done")}</span>
              </div>
            )}

            <button
              type="submit"
              className="submit-btn"
              disabled={!password || !password_confirmation || loading}
            >
              {loading ? <span className="loading-spinner"></span> : t("passwordPages.setPassword")}
            </button>
          </form>
        </div>

        <div className="login-footer">
          <span>&copy; {new Date().getFullYear()} SerOps. {t('login.allRightsReserved')}</span>
        </div>
      </div>
    </div>
  );
};

export default Password;

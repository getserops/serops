import React, { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import AuthService from "../services/auth.service";
import { FaEye, FaEyeSlash, FaEnvelope, FaLock, FaArrowRight, FaShieldAlt, FaCheckCircle } from "react-icons/fa";
import enterpriseSettingsService from "../services/enterpriseSettings.service";
import "./Login.css";
import { describeRequestError } from "../utils/apiError";
import BrandMark from './BrandMark';

const Login = () => {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [ssoLoading, setSsoLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const [error, setError] = useState("");
  const [emailError, setEmailError] = useState("");
  const [hidePassword, setHidePassword] = useState(true);
  const [resetSuccess, setResetSuccess] = useState(false);
  // Whether this deployment accepts open registration. Default true so
  // the "Create account" prompt shows until we hear back from the
  // backend — matches the self-hoster experience. Hidden demo hosts
  // like app.serops.ai return false and the prompt disappears.
  const [registrationEnabled, setRegistrationEnabled] = useState(true);
  // A seeded demo user exists: show "Try the live demo".
  const [demoAvailable, setDemoAvailable] = useState(false);
  // Public demo host: the demo is the only way in, so the form is hidden.
  const [demoOnly, setDemoOnly] = useState(false);

  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const autoDemo = useRef(false);

  useEffect(() => {
    // The SSO callback sends the browser back here when sign-in fails.
    if (searchParams.get("sso") === "failed") {
      setError(t('login.ssoSignInFailed'));
    }
  }, [searchParams, t]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      navigate("/dash");
    }
  }, [navigate]);

  useEffect(() => {
    // Fire-and-forget: any failure (network, 404 on old backends) keeps
    // the default (registration enabled) which is the safe assumption
    // for a self-hosted install.
    let cancelled = false;
    AuthService.registrationStatus()
      .then((r) => {
        if (cancelled || !r?.data) return;
        if (typeof r.data.registration_enabled === "boolean") {
          setRegistrationEnabled(r.data.registration_enabled);
        }
        setDemoAvailable(r.data.demo_available === true);
        setDemoOnly(r.data.demo_only === true);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && email && password && !emailError && !loading) {
      submit(e);
    }
  };

  const validateEmail = (email) => {
    const emailRegul = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegul.test(email);
  };

  const handleEmailChange = (e) => {
    const value = e.target.value;
    setEmail(value);
    setResetSuccess(false);
    if (value && !validateEmail(value)) {
      setEmailError(t('login.invalidEmail'));
    } else {
      setEmailError("");
    }
  };

  const submit = (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setResetSuccess(false);

    if (!validateEmail(email)) {
      setEmailError(t('login.invalidEmail'));
      setLoading(false);
      return;
    }

    AuthService.login(email, password)
      .then((response) => {
        localStorage.setItem("token", response.data.token);
        localStorage.setItem("user", JSON.stringify(response.data.user));
        navigate("/dash");
      })
      .catch((error) => {
        // Only call it a credentials problem when the server actually
        // refused them. A CORS block or an unreachable backend produces no
        // response at all, and telling the user their password is wrong
        // sends them to re-type something that was always correct.
        setError(describeRequestError(error, t('login.invalidCredentials')));
        setLoading(false);
      });
  };

  const handleForgot = (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setResetSuccess(false);

    if (!email) {
      setError(t('login.enterEmailFirst'));
      setLoading(false);
      return;
    }

    AuthService.password_forget(email)
      .then(() => {
        setError("");
        setResetSuccess(true);
      })
      .catch((error) => {
        setError(describeRequestError(error, t('login.somethingWrong')));
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const handleSSOLogin = async () => {
    if (!email || emailError) {
      setError(t('login.enterValidEmailForSSO'));
      return;
    }

    setSsoLoading(true);
    setError("");

    try {
      const response = await enterpriseSettingsService.initSSO(email);
      if (response.auth_url) {
        window.location.href = response.auth_url;
      } else {
        setError(t('login.ssoNotConfigured'));
      }
    } catch (err) {
      setError(describeRequestError(err, t('login.ssoFailed')));
    } finally {
      setSsoLoading(false);
    }
  };

  // One-click sign-in for the public read-only demo. Mirrors the
  // regular login flow: persist token + user, then redirect to /dash.
  // If the backend reports demo_not_configured (404), tell the user
  // rather than leaving them staring at a spinner.
  const handleDemoLogin = useCallback(async (source) => {
    setDemoLoading(true);
    setError("");
    try {
      const response = await AuthService.demoLogin(typeof source === "string" ? source : undefined);
      const { token, user } = response.data;
      localStorage.setItem("token", token);
      localStorage.setItem("user", JSON.stringify(user));
      // Reset the composed deployment filter — a returning user might
      // have a cluster / env / region / namespace saved in localStorage
      // from their own org that doesn't match the demo org's shape, in
      // which case dashboards silently show zero data. Fresh demo
      // sessions always start unfiltered.
      localStorage.removeItem("serops.deployment.filter");
      localStorage.removeItem("serops.cluster.selected");
      navigate("/dash");
    } catch (err) {
      const code = err.response?.data?.error;
      if (code === 'demo_not_configured') {
        setError(t('login.demoNotConfigured'));
      } else {
        setError(describeRequestError(err, t('login.demoFailed')));
      }
    } finally {
      setDemoLoading(false);
    }
  }, [navigate, t]);

  // /login?demo=1 (the landing page's "Try the live demo") opens the demo
  // straight away instead of asking for a second click. Ignored where no
  // demo is seeded.
  useEffect(() => {
    if (demoAvailable && searchParams.get("demo") === "1" && !autoDemo.current) {
      autoDemo.current = true;
      handleDemoLogin(searchParams.get("src"));
    }
  }, [demoAvailable, searchParams, handleDemoLogin]);

  return (
    <div className="login-page">
      <div className="login-form-panel">
        <div className="form-container">
          {demoOnly ? (
            <div className="login-form">
              <div className="form-header">
                <BrandMark className="form-logo" />
                <h2>{t('login.demoOnlyTitle')}</h2>
                <p>{t('login.demoOnlyText')}</p>
              </div>
              {error && (
                <div className="alert-error">
                  <span>{error}</span>
                </div>
              )}
              <button
                type="button"
                className="submit-btn"
                onClick={handleDemoLogin}
                disabled={demoLoading}
              >
                {demoLoading ? (
                  <span className="loading-spinner"></span>
                ) : (
                  <>
                    {t('login.tryDemo')}
                    <FaArrowRight className="btn-icon" />
                  </>
                )}
              </button>
              <div className="register-prompt">
                <a
                  href="https://serops.ai/docs/getting-started/quick-start-self-hosted/"
                  className="register-prompt-link"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t('login.selfHost')}
                </a>
              </div>
            </div>
          ) : (
            <>
              <div className="form-header">
                <BrandMark className="form-logo" />
                <h2>{t('login.welcomeBack')}</h2>
                <p>{t('login.enterCredentials')}</p>
              </div>
            <form onSubmit={submit} className="login-form">
              <div className="form-group">
                <label htmlFor="email">{t('login.emailAddress')}</label>
                <div className="input-wrapper">
                  <FaEnvelope className="input-icon" />
                  <input
                    type="email"
                    id="email"
                    placeholder={t('login.emailPlaceholder')}
                    value={email}
                    onChange={handleEmailChange}
                    onKeyDown={handleKeyDown}
                    className={emailError ? "error" : ""}
                    autoComplete="email"
                  />
                </div>
                {emailError && <span className="error-text">{emailError}</span>}
              </div>

              <div className="form-group">
                <div className="label-row">
                  <label htmlFor="password">{t('auth.password')}</label>
                  <button
                    type="button"
                    className="forgot-link"
                    onClick={handleForgot}
                  >
                    {t('auth.forgotPassword')}
                  </button>
                </div>
                <div className="input-wrapper">
                  <FaLock className="input-icon" />
                  <input
                    type={hidePassword ? "password" : "text"}
                    id="password"
                    placeholder={t('login.passwordPlaceholder')}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={handleKeyDown}
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    className="toggle-password"
                    onClick={() => setHidePassword(!hidePassword)}
                    aria-label={hidePassword ? t('login.showPassword') : t('login.hidePassword')}
                  >
                    {hidePassword ? <FaEyeSlash /> : <FaEye />}
                  </button>
                </div>
              </div>

              {resetSuccess && (
                <div className="alert-success">
                  <FaCheckCircle />
                  <span>{t('login.resetSuccess')}</span>
                </div>
              )}

              {error && (
                <div className="alert-error">
                  <span>{error}</span>
                </div>
              )}

              <button
                type="submit"
                className="submit-btn"
                disabled={!email || emailError || !password || loading}
              >
                {loading ? (
                  <span className="loading-spinner"></span>
                ) : (
                  <>
                    {t('login.signIn')}
                    <FaArrowRight className="btn-icon" />
                  </>
                )}
              </button>

              <div className="sso-divider">
                <span>{t('login.or')}</span>
              </div>

              <button
                type="button"
                className="sso-btn"
                onClick={handleSSOLogin}
                disabled={!email || emailError || loading || ssoLoading}
              >
                {ssoLoading ? <span className="loading-spinner"></span> : <FaShieldAlt className="btn-icon-left" />}
                {t('login.loginWithSSO')}
              </button>

              {/* One-click read-only demo, only where one is seeded. */}
              {demoAvailable && (
                <button
                  type="button"
                  className="sso-btn"
                  onClick={handleDemoLogin}
                  disabled={loading || ssoLoading || demoLoading}
                >
                  {demoLoading
                    ? <span className="loading-spinner"></span>
                    : <FaArrowRight className="btn-icon-left" />}
                  {t('login.tryDemo')}
                </button>
              )}

              {registrationEnabled ? (
                <div className="register-prompt">
                  <div className="register-prompt-row">
                    <span className="register-prompt-label">{t('login.haveInviteCode')}</span>
                    <button
                      type="button"
                      className="register-prompt-link"
                      onClick={() => navigate('/register')}
                    >
                      {t('login.createAccount')}
                    </button>
                  </div>
                  <a
                    href="https://serops.ai"
                    className="waitlist-link"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t('login.joinWaitlist')}
                  </a>
                </div>
              ) : (
                // Registration is closed on this deployment (e.g. the
                // public demo host). Point visitors at the self-host
                // docs so the outcome is not a dead end.
                <div className="register-prompt">
                  <a
                    href="https://serops.ai/docs/getting-started/quick-start-self-hosted/"
                    className="register-prompt-link"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {t('login.selfHost')}
                  </a>
                </div>
              )}
            </form>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="login-footer">
          <span>&copy; {new Date().getFullYear()} SerOps. {t('login.allRightsReserved')}</span>
        </div>
      </div>
    </div>
  );
};

export default Login;

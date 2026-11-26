import React, { useState, useEffect } from "react";
import { describeRequestError } from "../utils/apiError";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import AuthService from "../services/auth.service";
import "./Login.css";
import { FaUser, FaEnvelope, FaBuilding, FaLock, FaArrowRight, FaArrowLeft, FaEye, FaEyeSlash } from "react-icons/fa";
import BrandMark from './BrandMark';

// How long the page waits for the registration status before showing the form.
export const REGISTRATION_STATUS_WAIT_MS = 4000;

const Register = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // State
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Form Data
  const [formData, setFormData] = useState({
    user: {
      first_name: "",
      last_name: "",
      email: "",
      phone: "",
      password: "",
      password_confirmation: "",
    },
    organisation: {
      name: "",
    },
  });

  // UI State
  const [hidePassword, setHidePassword] = useState(true);
  const [fieldErrors, setFieldErrors] = useState({});

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      navigate("/dash");
    }
  }, [navigate]);

  // Whether this instance accepts sign-ups, asked before the form shows (as
  // the login page does). Closed: say so and offer sign-in, instead of a
  // form the server refuses at the last step. No answer, an old server or a
  // slow one: the form, as before (the server still refuses).
  const [signup, setSignup] = useState("checking");
  useEffect(() => {
    let settled = false;
    const settle = (value) => {
      if (settled) return;
      settled = true;
      setSignup(value);
    };
    const fallback = setTimeout(() => settle("open"), REGISTRATION_STATUS_WAIT_MS);
    AuthService.registrationStatus()
      .then((r) => settle(r?.data?.registration_enabled === false ? "closed" : "open"))
      .catch(() => settle("open"));
    return () => {
      settled = true;
      clearTimeout(fallback);
    };
  }, []);

  // Handlers
  const handleChange = (e) => {
    const { name, value } = e.target;

    // Handle nested state updates
    if (name === "name") {
      setFormData(prev => ({
        ...prev,
        organisation: { ...prev.organisation, name: value }
      }));
    } else {
      setFormData(prev => ({
        ...prev,
        user: { ...prev.user, [name]: value }
      }));
    }

    // Clear error for this field
    if (fieldErrors[name]) {
      setFieldErrors(prev => ({ ...prev, [name]: "" }));
    }
  };

  // Validation
  const validateStep1 = () => {
    const errors = {};
    const { user, organisation } = formData;

    if (!user.first_name) errors.first_name = t("register.firstNameRequired");
    if (!user.last_name) errors.last_name = t("register.lastNameRequired");
    if (!organisation.name) errors.name = t("register.companyRequired");
    // Invite code validation is handled server-side (only required when BETA_INVITE_CODE is set)

    if (!user.email) {
      errors.email = t("register.emailRequired");
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(user.email)) {
      errors.email = t("register.invalidEmail");
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const validateStep2 = () => {
    const errors = {};
    const { user } = formData;
    const passwordRegex = /^(?=.*\d)(?=.*[a-z])(?=.*[A-Z]).{10,}$/;

    if (!user.password) {
      errors.password = t("register.passwordRequired");
    } else if (!passwordRegex.test(user.password)) {
      errors.password = t("register.passwordRule");
    }

    if (user.password !== user.password_confirmation) {
      errors.password_confirmation = t("register.passwordsMismatch");
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleNext = (e) => {
    e.preventDefault();
    if (step === 1 && validateStep1()) {
      setStep(2);
    }
  };

  const handleBack = () => {
    setStep(1);
    setError("");
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!validateStep2()) return;

    setLoading(true);
    setError("");

    AuthService.register(formData)
      .then((response) => {
        if (response.data.token) {
          localStorage.setItem("token", response.data.token);
        }
        if (response.data.user) {
          localStorage.setItem("user", JSON.stringify(response.data.user));
        }
        if (response.data.token) {
          navigate("/dash");
        } else if (response.data.email_sent !== undefined) {
          // Activation by email: say so, and say when the email did not go
          // out. Sign-up used to land on Login without a word (journey
          // suite, B1 and B11).
          navigate("/register_verif", {
            state: { email: formData.user.email, emailSent: response.data.email_sent, message: response.data.message },
          });
        } else {
          navigate("/login", { state: { message: response.data.message } });
        }
      })
      .catch((error) => {
        setError(describeRequestError(error, t("register.failed")));
        setLoading(false);
      });
  };

  if (signup !== "open") {
    return (
      <div className="login-page">
        <div className="login-form-panel">
          <div className="form-container">
            {signup === "checking" ? (
              <div className="form-header" aria-busy="true">
                <BrandMark className="form-logo" />
                <span className="loading-spinner" role="status" aria-label={t("common.loading")}></span>
              </div>
            ) : (
              <>
                <div className="form-header">
                  <BrandMark className="form-logo" />
                  <h2>{t("register.closedTitle")}</h2>
                  <p>{t("register.closedMessage")}</p>
                </div>
                <div className="login-form">
                  <div className="sso-divider">
                    <span>{t("auth.hasAccount")}</span>
                  </div>
                  <Link to="/login" className="sso-btn">
                    {t("login.signIn")}
                  </Link>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="login-page">
      <div className="login-form-panel">
        <div className="form-container">
          <div className="form-header">
            <BrandMark className="form-logo" />
            <h2>{step === 1 ? t("register.createAccount") : t("register.secureTitle")}</h2>
            <p>
              {step === 1
                ? t("register.detailsSubtitle")
                : t("register.passwordSubtitle")}
            </p>
          </div>

          <form onSubmit={step === 1 ? handleNext : handleSubmit} className="login-form">

            {step === 1 && (
              <>
                <div className="label-row register-name-row">
                  <div className="form-group register-name-field">
                    <label htmlFor="register-first_name">{t("team.firstName")}</label>
                    <div className="input-wrapper">
                      <FaUser className="input-icon" />
                      <input
                        id="register-first_name"
                        type="text"
                        name="first_name"
                        placeholder="John"
                        value={formData.user.first_name}
                        onChange={handleChange}
                        className={fieldErrors.first_name ? "error" : ""}
                      />
                    </div>
                  </div>
                  <div className="form-group register-name-field">
                    <label htmlFor="register-last_name">{t("team.lastName")}</label>
                    <div className="input-wrapper">
                      <input
                        id="register-last_name"
                        type="text"
                        name="last_name"
                        placeholder="Doe"
                        value={formData.user.last_name}
                        onChange={handleChange}
                        className={fieldErrors.last_name ? "error" : ""}
                      />
                    </div>
                  </div>
                </div>
                {(fieldErrors.first_name || fieldErrors.last_name) &&
                  <div className="error-text">{t("register.nameRequired")}</div>}

                <div className="form-group">
                  <label htmlFor="register-email">{t("register.workEmail")}</label>
                  <div className="input-wrapper">
                    <FaEnvelope className="input-icon" />
                    <input
                      id="register-email"
                      type="email"
                      name="email"
                      placeholder="john@company.com"
                      value={formData.user.email}
                      onChange={handleChange}
                      className={fieldErrors.email ? "error" : ""}
                    />
                  </div>
                  {fieldErrors.email && <span className="error-text">{fieldErrors.email}</span>}
                </div>

                <div className="form-group">
                  <label htmlFor="register-name">{t("register.companyName")}</label>
                  <div className="input-wrapper">
                    <FaBuilding className="input-icon" />
                    <input
                      id="register-name"
                      type="text"
                      name="name"
                      placeholder="Acme Corp"
                      value={formData.organisation.name}
                      onChange={handleChange}
                      className={fieldErrors.name ? "error" : ""}
                    />
                  </div>
                  {fieldErrors.name && <span className="error-text">{fieldErrors.name}</span>}
                </div>

                <button type="submit" className="submit-btn submit-btn-spaced">
                  {t("register.continue")} <FaArrowRight className="btn-icon" />
                </button>
              </>
            )}

            {step === 2 && (
              <>
                <button type="button" onClick={handleBack} className="back-step-link">
                  <FaArrowLeft /> {t("register.backToDetails")}
                </button>

                <div className="form-group">
                  <label htmlFor="register-password">{t("auth.password")}</label>
                  <div className="input-wrapper">
                    <FaLock className="input-icon" />
                    <input
                      id="register-password"
                      type={hidePassword ? "password" : "text"}
                      name="password"
                      placeholder={t("register.passwordPlaceholder")}
                      value={formData.user.password}
                      onChange={handleChange}
                      className={fieldErrors.password ? "error" : ""}
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      className="toggle-password"
                      aria-label={hidePassword ? t("login.showPassword") : t("login.hidePassword")}
                      onClick={() => setHidePassword(!hidePassword)}
                    >
                      {hidePassword ? <FaEyeSlash /> : <FaEye />}
                    </button>
                  </div>
                  <span className="field-hint">
                    {t("register.passwordHint")}
                  </span>
                  {fieldErrors.password && <span className="error-text">{fieldErrors.password}</span>}
                </div>

                <div className="form-group">
                  <label htmlFor="register-password_confirmation">{t("register.confirmPassword")}</label>
                  <div className="input-wrapper">
                    <FaLock className="input-icon" />
                    <input
                      id="register-password_confirmation"
                      type="password"
                      name="password_confirmation"
                      placeholder={t("register.repeatPassword")}
                      value={formData.user.password_confirmation}
                      onChange={handleChange}
                      className={fieldErrors.password_confirmation ? "error" : ""}
                      autoComplete="new-password"
                    />
                  </div>
                  {fieldErrors.password_confirmation && <span className="error-text">{fieldErrors.password_confirmation}</span>}
                </div>

                {error && <div className="alert-error">{error}</div>}

                <button type="submit" className="submit-btn submit-btn-spaced" disabled={loading}>
                  {loading ? <span className="loading-spinner"></span> : t("register.createAccount")}
                </button>
              </>
            )}

            <div className="sso-divider">
              <span>{t("auth.hasAccount")}</span>
            </div>

            <button type="button" className="sso-btn" onClick={() => navigate('/login')}>
              {t("login.signIn")}
            </button>

          </form>
        </div>

        <div className="login-footer">
          <span>{t("register.agreeTerms")}</span>
        </div>
      </div>
    </div>
  );
};

export default Register;

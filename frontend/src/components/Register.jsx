import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import AuthService from "../services/auth.service";
import "./Login.css";
import { FaUser, FaEnvelope, FaBuilding, FaLock, FaArrowRight, FaArrowLeft, FaEye, FaEyeSlash } from "react-icons/fa";

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

    if (!user.first_name) errors.first_name = "First name is required";
    if (!user.last_name) errors.last_name = "Last name is required";
    if (!organisation.name) errors.name = "Company name is required";
    // Invite code validation is handled server-side (only required when BETA_INVITE_CODE is set)

    if (!user.email) {
      errors.email = "Email is required";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(user.email)) {
      errors.email = "Invalid email format";
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const validateStep2 = () => {
    const errors = {};
    const { user } = formData;
    const passwordRegex = /^(?=.*\d)(?=.*[a-z])(?=.*[A-Z]).{10,}$/;

    if (!user.password) {
      errors.password = "Password is required";
    } else if (!passwordRegex.test(user.password)) {
      errors.password = "Must be 10+ chars, 1 uppercase, 1 lowercase, 1 number";
    }

    if (user.password !== user.password_confirmation) {
      errors.password_confirmation = "Passwords do not match";
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
        navigate("/dash");
      })
      .catch((error) => {
        setError(error.response?.data?.message || "Registration failed");
        setLoading(false);
      });
  };

  return (
    <div className="login-page">
      <div className="login-form-panel">
        <div className="form-container">
          <div className="form-header">
            <img src="/assets/images/Serops-Logo.png" alt="SerOps" className="form-logo" />
            <h2>{step === 1 ? "Create Account" : "Secure your account"}</h2>
            <p>
              {step === 1
                ? "Enter your details to get started"
                : "Set a strong password to protect your data"}
            </p>
          </div>

          <form onSubmit={step === 1 ? handleNext : handleSubmit} className="login-form">

            {step === 1 && (
              <>
                <div className="label-row register-name-row">
                  <div className="form-group register-name-field">
                    <label>First Name</label>
                    <div className="input-wrapper">
                      <FaUser className="input-icon" />
                      <input
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
                    <label>Last Name</label>
                    <div className="input-wrapper">
                      <input
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
                  <div className="error-text">Name is required</div>}

                <div className="form-group">
                  <label>Work Email</label>
                  <div className="input-wrapper">
                    <FaEnvelope className="input-icon" />
                    <input
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
                  <label>Company Name</label>
                  <div className="input-wrapper">
                    <FaBuilding className="input-icon" />
                    <input
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
                  Continue <FaArrowRight className="btn-icon" />
                </button>
              </>
            )}

            {step === 2 && (
              <>
                <button type="button" onClick={handleBack} className="back-step-link">
                  <FaArrowLeft /> Back to details
                </button>

                <div className="form-group">
                  <label>Password</label>
                  <div className="input-wrapper">
                    <FaLock className="input-icon" />
                    <input
                      type={hidePassword ? "password" : "text"}
                      name="password"
                      placeholder="Create a strong password"
                      value={formData.user.password}
                      onChange={handleChange}
                      className={fieldErrors.password ? "error" : ""}
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      className="toggle-password"
                      onClick={() => setHidePassword(!hidePassword)}
                    >
                      {hidePassword ? <FaEyeSlash /> : <FaEye />}
                    </button>
                  </div>
                  <span className="field-hint">
                    Must be at least 10 characters, include 1 uppercase, 1 lowercase letter and 1 number.
                  </span>
                  {fieldErrors.password && <span className="error-text">{fieldErrors.password}</span>}
                </div>

                <div className="form-group">
                  <label>Confirm Password</label>
                  <div className="input-wrapper">
                    <FaLock className="input-icon" />
                    <input
                      type="password"
                      name="password_confirmation"
                      placeholder="Repeat password"
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
                  {loading ? <span className="loading-spinner"></span> : "Create Account"}
                </button>
              </>
            )}

            <div className="sso-divider">
              <span>Already have an account?</span>
            </div>

            <button type="button" className="sso-btn" onClick={() => navigate('/login')}>
              Sign In
            </button>

          </form>
        </div>

        <div className="login-footer">
          <span>By signing up, you agree to our Terms and Privacy Policy.</span>
        </div>
      </div>
    </div>
  );
};

export default Register;

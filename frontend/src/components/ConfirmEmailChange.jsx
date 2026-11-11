import React, { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FaEnvelope } from "react-icons/fa";
import AuthService from "../services/auth.service";
import { describeRequestError } from "../utils/apiError";
import BrandMark from "./BrandMark";
import "./Login.css";

// A button rather than a request on load: mail scanners open links.
function ConfirmEmailChange() {
  const { t } = useTranslation();
  const { token } = useParams();
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");

  const confirm = () => {
    setState("working");
    setError("");
    AuthService.confirm_email_change(token)
      .then(() => {
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        setState("done");
      })
      .catch((err) => {
        setError(describeRequestError(err, t("emailConfirm.failed")));
        setState("idle");
      });
  };

  return (
    <div className="login-page">
      <div className="login-form-panel">
        <div className="form-container">
          <div className="form-header">
            <BrandMark className="form-logo" />
            <div style={{ display: "flex", justifyContent: "center", marginBottom: "0.5rem" }}>
              <FaEnvelope size={36} style={{ color: "var(--primary-500)" }} />
            </div>
            <h2>{t("emailConfirm.title")}</h2>
            <p>{state === "done" ? t("emailConfirm.done") : t("emailConfirm.intro")}</p>
          </div>

          {error && <div className="alert-error"><span>{error}</span></div>}

          {state === "done" ? (
            <Link className="submit-btn" to="/login" style={{ marginTop: "1rem", textAlign: "center", display: "block" }}>
              {t("emailConfirm.signIn")}
            </Link>
          ) : (
            <button type="button" className="submit-btn" onClick={confirm} disabled={state === "working"} style={{ marginTop: "1rem" }}>
              {state === "working" ? t("emailConfirm.working") : t("emailConfirm.button")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default ConfirmEmailChange;

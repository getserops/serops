import React, { useState, useEffect } from "react";
import "./Login.css";
import { useNavigate, useParams } from "react-router-dom";
import { FaEnvelope } from "react-icons/fa";
import AuthService from "../services/auth.service";

function Invitation() {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [success, setSuccess] = useState(false);
  const { string } = useParams();
  const navigate = useNavigate();

  useEffect(() => {
    AuthService.accept_invitation(string)
      .then(() => {
        // Stash the invitation JWT (not the user id) so the Password
        // page can pass it back to the server. Backend decodes the
        // token to derive user_id — the prior localStorage('id')
        // pattern let anyone submit any user_id (account-takeover
        // vector fixed 2026-08-30). sessionStorage clears on tab
        // close so a shared browser doesn't leak the token later.
        sessionStorage.setItem('invitation_token', string);
        setSuccess(true);
      })
      .catch((err) => {
        setError(err?.response?.data?.message || "Invitation failed");
      })
      .finally(() => setLoading(false));
  }, [string]);

  const handleSetPassword = () => navigate('/invitation_password');

  return (
    <div className="login-page">
      <div className="login-form-panel">
        <div className="form-container">
          <div className="form-header">
            <img src="/assets/images/Serops-Logo.png" alt="SerOps" className="form-logo" />
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.5rem' }}>
              <FaEnvelope size={36} style={{ color: 'var(--primary-500)' }} />
            </div>
            <h2>Accept invitation</h2>
            <p>
              {loading
                ? "Processing your invitation…"
                : success
                ? "Your invitation is accepted. Set a password to finish."
                : "We couldn't process your invitation."}
            </p>
          </div>

          {error && !loading && (
            <div className="alert-error"><span>{error}</span></div>
          )}

          {success && (
            <button
              type="button"
              className="submit-btn"
              onClick={handleSetPassword}
              style={{ marginTop: '1rem' }}
            >
              Set password
            </button>
          )}
        </div>

        <div className="login-footer">
          <span>&copy; {new Date().getFullYear()} SerOps. All rights reserved.</span>
        </div>
      </div>
    </div>
  );
}

export default Invitation;

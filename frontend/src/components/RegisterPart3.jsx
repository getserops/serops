import React from 'react';
import '../Styles/Register.css';
import './Login.css';
import { useNavigate } from 'react-router';
import { FaCheckCircle } from 'react-icons/fa';
import AuthService from "../services/auth.service";

function RegisterPart3() {
  const navigate = useNavigate();
  const handleResendEmail = () => {
    AuthService.resendVerify()
      .then(() => {})
      .catch((error) => console.error('Failed to resend email:', error));
  };
  const handleSignIn = () => navigate('/login');

  return (
    <div className="login-page">
      <div className="login-form-panel">
        <div className="form-container">
          <div className="form-header">
            <img src="/assets/images/Serops-Logo.png" alt="SerOps" className="form-logo" />
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.5rem' }}>
              <FaCheckCircle size={40} style={{ color: 'var(--success-500)' }} />
            </div>
            <h2>Verify by email</h2>
            <p>
              Check your inbox and follow the link we sent to finish creating your
              account. Didn't get it? Resend below.
            </p>
          </div>

          <div className="login-form">
            <button
              type="button"
              className="btn btn-primary ds-btn ds-btn-primary ds-btn-full"
              onClick={handleResendEmail}
            >
              Resend verification email
            </button>
            <button
              type="button"
              className="sso-btn ds-btn ds-btn-secondary ds-btn-full"
              onClick={handleSignIn}
              style={{ marginTop: '0.5rem' }}
            >
              Back to sign in
            </button>
          </div>
        </div>

        <div className="login-footer">
          <span>&copy; {new Date().getFullYear()} SerOps. All rights reserved.</span>
        </div>
      </div>
    </div>
  );
}

export default RegisterPart3;

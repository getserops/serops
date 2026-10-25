import React from 'react';
import '../Styles/Register.css';
import './Login.css';
import { useLocation, useNavigate } from 'react-router-dom';
import { FaCheckCircle, FaExclamationTriangle } from 'react-icons/fa';
import BrandMark from './BrandMark';

function RegisterPart3() {
  const navigate = useNavigate();
  const { state } = useLocation();
  const emailFailed = state?.emailSent === false;
  const handleSignIn = () => navigate('/login');

  return (
    <div className="login-page">
      <div className="login-form-panel">
        <div className="form-container">
          <div className="form-header">
            <BrandMark className="form-logo" />
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '0.5rem' }}>
              {emailFailed
                ? <FaExclamationTriangle size={40} aria-hidden="true" style={{ color: 'var(--warning-500)' }} />
                : <FaCheckCircle size={40} aria-hidden="true" style={{ color: 'var(--success-500)' }} />}
            </div>
            <h2>{emailFailed ? 'Account created, email not sent' : 'Verify by email'}</h2>
            {emailFailed ? (
              <p role="alert">{state.message}</p>
            ) : (
              <p>
                Check your inbox: we sent an activation link{state?.email ? <> to <strong>{state.email}</strong></> : null}.
                Follow it to finish creating your account. Nothing after a few minutes?
                Check your spam folder, or ask your SerOps administrator.
              </p>
            )}
          </div>

          <div className="login-form">
            <button
              type="button"
              className="btn btn-primary ds-btn ds-btn-primary ds-btn-full"
              onClick={handleSignIn}
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

import React from 'react';
import '../Styles/Register.css';
import './Login.css';
import { useLocation, useNavigate } from 'react-router-dom';
import { FaCheckCircle, FaExclamationTriangle } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import BrandMark from './BrandMark';

function RegisterPart3() {
  const { t } = useTranslation();
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
            <h2>{emailFailed ? t('registerPart3.emailNotSentTitle') : t('registerPart3.verifyTitle')}</h2>
            {emailFailed ? (
              <p role="alert">{state.message}</p>
            ) : (
              <p>
                {t('registerPart3.sentBefore')}{state?.email ? <>{t('registerPart3.sentTo')}<strong>{state.email}</strong></> : null}{t('registerPart3.sentAfter')}
              </p>
            )}
          </div>

          <div className="login-form">
            <button
              type="button"
              className="btn btn-primary ds-btn ds-btn-primary ds-btn-full"
              onClick={handleSignIn}
            >
              {t('registerPart3.backToSignIn')}
            </button>
          </div>
        </div>

        <div className="login-footer">
          <span>&copy; {new Date().getFullYear()} SerOps. {t('login.allRightsReserved')}</span>
        </div>
      </div>
    </div>
  );
}

export default RegisterPart3;

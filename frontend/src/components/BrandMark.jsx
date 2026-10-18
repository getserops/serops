import React from 'react';
import SerOpsMark from './SerOpsMark';

// The SerOps mark + wordmark, the same as the app sidebar and serops.ai. Used on the
// signed-out pages (sign in, sign up, invitation, password reset).
const BrandMark = ({ className = '' }) => (
  <div className={`brand-mark ${className}`} role="img" aria-label="SerOps">
    <SerOpsMark size={32} className="brand-mark-icon" />
    <span className="brand-mark-word" aria-hidden="true">SerOps</span>
  </div>
);

export default BrandMark;

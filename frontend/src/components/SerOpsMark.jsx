import React from 'react';

// The SerOps "SO" mark: the white S and the mint dot on the brand-blue
// double circle, cut from the original logo artwork (Serops-Logo.png).
// `size` is its height; the mark is wider than tall (253 × 161).
const RATIO = 253 / 161;

const SerOpsMark = ({ size = 28, className = '' }) => (
  <img
    className={`serops-mark ${className}`}
    src="/assets/images/serops-mark.png"
    width={Math.round(size * RATIO)}
    height={size}
    alt=""
    aria-hidden="true"
    draggable="false"
  />
);

export default SerOpsMark;

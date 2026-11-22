import React, { useLayoutEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { isDemoUser } from '../utils/demo';

export const BENCHMARK_URL = 'https://serops.ai/benchmark';
export const DISMISSED_KEY = 'serops.demoBannerDismissed';
// Layouts that fill the screen (the chat) subtract this from their height.
const HEIGHT_VAR = '--demo-banner-h';

const wasDismissed = () => {
  try { return window.sessionStorage.getItem(DISMISSED_KEY) === '1'; } catch { return false; }
};

// Says what the public demo shows, on every signed-in page. The demo holds
// only analyses SerOps got right (incidents and two healthy windows), so
// the sentence points to the page that has the runs it missed. A visitor can
// close it for the session (it is back at the next visit). Its height is
// published as --demo-banner-h on <html>, 0px when it is not shown.
// Renders nothing for any other user.
const DemoBanner = () => {
  const { t } = useTranslation();
  const ref = useRef(null);
  const [dismissed, setDismissed] = useState(wasDismissed);
  const shown = isDemoUser() && !dismissed;

  useLayoutEffect(() => {
    const root = document.documentElement;
    const el = ref.current;
    if (!shown || !el) {
      root.style.setProperty(HEIGHT_VAR, '0px');
      return undefined;
    }
    const publish = () => root.style.setProperty(HEIGHT_VAR, `${el.offsetHeight}px`);
    publish();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(publish);
    if (observer) observer.observe(el);
    return () => {
      if (observer) observer.disconnect();
      root.style.setProperty(HEIGHT_VAR, '0px');
    };
  }, [shown]);

  if (!shown) return null;
  const dismiss = () => {
    try { window.sessionStorage.setItem(DISMISSED_KEY, '1'); } catch { /* private mode: closed for this page only */ }
    setDismissed(true);
  };
  return (
    <div className="demo-banner" role="status" ref={ref}>
      <span>
        {t('demo.banner.before')}
        <a href={BENCHMARK_URL} target="_blank" rel="noopener noreferrer">{t('demo.banner.link')}</a>
        {t('demo.banner.after')}
      </span>
      <a
        href="https://serops.ai/docs/getting-started/quick-start-self-hosted/"
        target="_blank"
        rel="noopener noreferrer"
      >
        {t('demo.banner.selfHost')}
      </a>
      <button type="button" className="demo-banner-close" onClick={dismiss} aria-label={t('common.close')} title={t('common.close')}>
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
};

export default DemoBanner;

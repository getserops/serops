import React from 'react';
import { useTranslation } from 'react-i18next';
import { isDemoUser } from '../utils/demo';

export const BENCHMARK_URL = 'https://serops.ai/benchmark';

// Says what the public demo shows, on every signed-in page. The demo holds
// only analyses SerOps got right (incidents and two healthy windows), so
// the sentence points to the page that has the runs it missed. Renders nothing for any other user.
const DemoBanner = () => {
  const { t } = useTranslation();
  if (!isDemoUser()) return null;
  return (
    <div className="demo-banner" role="status">
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
    </div>
  );
};

export default DemoBanner;

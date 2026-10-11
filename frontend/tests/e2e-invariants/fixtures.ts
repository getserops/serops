/**
 * Canonical list of UI fixture batches — matches
 * ``backend/tests_gauntlet/seed_ui_fixtures.py::UI_FIXTURE_BATCHES``.
 *
 * Every entry has a stable ``batch_id`` so the invariants can loop
 * against known-good pages. Re-seed via:
 *
 *   docker exec serops-backend python -m tests_gauntlet.seed_ui_fixtures
 */

export interface UiFixture {
  batchId: string;
  /** Short label surfaced in Playwright test titles. */
  label: string;
  /** What real-world hostile shape this covers. */
  covers: string;
}

export const UI_FIXTURES: UiFixture[] = [
  { batchId: 'gt-ui-s1-pii',        label: 'PII in logs',              covers: 'PII redaction chain' },
  { batchId: 'gt-ui-s3-injection',  label: 'Prompt injection',         covers: 'Attacker payloads in logs' },
  { batchId: 'gt-ui-c1-cascade',    label: '5-hop cascade',            covers: 'Long-narrative rendering' },
  { batchId: 'gt-ui-cd5-no-deploy', label: 'No fabricated deploy',     covers: 'Empty code_changes' },
  { batchId: 'gt-ui-sn1-quiet',     label: 'Sentinel QUIET',           covers: 'AI-skipped empty state' },
  { batchId: 'gt-ui-e1-herrings',   label: 'Real + herrings',          covers: 'Many-issues list' },
  { batchId: 'gt-ui-a2-multiline',  label: 'Java multi-line stacks',   covers: 'Dedup + long log lines' },
  { batchId: 'gt-ui-h1-rollback',   label: 'Rollback deploy window',   covers: 'code_changes commit list' },
  { batchId: 'gt-ui-with-history',  label: 'Compare panel + Promote',  covers: 'analysis_history rendering' },
  { batchId: 'gt-ui-alt-model',     label: 'Alt-model narrative',      covers: 'Model diversity' },
];

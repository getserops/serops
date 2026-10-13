/**
 * AIBudgetCard — Monthly AI cost cap + live spend gauge (Batch 47).
 *
 * Backend was shipped in Batch 26 but the UI was deferred — up to now
 * the only way to see current spend or set a budget was via curl. This
 * closes that gap.
 *
 * Composition:
 *   * Current-spend progress bar keyed off warn/exceeded thresholds
 *     (blue → yellow at warn_threshold_pct → red at 100%).
 *   * Editable inputs for ``monthly_budget_usd`` (blank = unlimited)
 *     and ``budget_warn_pct`` (0-100, default 80).
 *   * Save button PUTs through the existing /settings/ai/ endpoint
 *     (Batch 26 already added the two fields to the serializer).
 *
 * Fail-open UX: if the budget-status fetch fails, we render the
 * inputs with sensible defaults and let the user save. Never render
 * "AI paused" from a fetch error alone — that would misinform.
 */

import React, { useState, useEffect } from 'react';
import { Card, Form, Button, ProgressBar, Alert, Badge, Spinner } from 'react-bootstrap';
import { FaDollarSign, FaExclamationTriangle, FaCheckCircle, FaInfoCircle } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import SettingsService from '../../services/settings.service';

const formatUsd = (raw) => {
    if (raw == null || raw === '') return '—';
    const n = parseFloat(raw);
    if (!Number.isFinite(n)) return '—';
    return `$${n.toFixed(2)}`;
};

const formatMonth = (iso) => {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        return d.toLocaleString(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' });
    } catch {
        return '';
    }
};

const AIBudgetCard = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [status, setStatus] = useState(null);          // snapshot from GET
    const [budgetInput, setBudgetInput] = useState(''); // string so blank = unlimited
    const [warnInput, setWarnInput] = useState(80);

    const loadStatus = async () => {
        setLoading(true);
        try {
            const data = await SettingsService.getAIBudgetStatus();
            setStatus(data);
            setBudgetInput(data.monthly_budget_usd != null ? String(parseFloat(data.monthly_budget_usd).toFixed(2)) : '');
            setWarnInput(data.warn_threshold_pct ?? 80);
        } catch (err) {
            // Fail-open: leave inputs at their defaults so the user can
            // still SET a budget even if the read failed for other reasons.
            setStatus(null);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadStatus();
    }, []);

    const handleSave = async () => {
        setSaving(true);
        try {
            // Blank input means "unlimited" — send null explicitly so the
            // backend clears any prior cap. Numeric conversion here so
            // we don't send strings the DecimalField coerce loosely on.
            const payload = {
                monthly_budget_usd: budgetInput === '' ? null : parseFloat(budgetInput),
                budget_warn_pct: parseInt(warnInput, 10) || 80,
            };
            if (payload.monthly_budget_usd != null && payload.monthly_budget_usd < 0) {
                toast.warning(t('ai.budgetNegative', 'Budget must be zero or positive.'));
                setSaving(false);
                return;
            }
            if (payload.budget_warn_pct < 0 || payload.budget_warn_pct > 100) {
                toast.warning(t('ai.warnPctRange', 'Warn threshold must be 0-100.'));
                setSaving(false);
                return;
            }
            await SettingsService.updateAISettings(payload);
            toast.success(t('ai.budgetSaved', 'Budget updated.'));
            // Refresh the gauge so the new budget/warn are reflected.
            await loadStatus();
        } catch (err) {
            const msg = err.response?.data?.error
                || err.response?.data?.monthly_budget_usd?.[0]
                || err.response?.data?.budget_warn_pct?.[0]
                || t('ai.budgetSaveFailed', 'Failed to save budget.');
            toast.error(msg);
        } finally {
            setSaving(false);
        }
    };

    // Derived rendering state
    const budgetNum = status?.monthly_budget_usd != null ? parseFloat(status.monthly_budget_usd) : null;
    const spendNum = parseFloat(status?.current_spend_usd ?? '0');
    const pct = budgetNum && budgetNum > 0 ? Math.min(999, (spendNum / budgetNum) * 100) : 0;
    const barVariant = status?.is_exceeded ? 'danger' : status?.is_warning ? 'warning' : 'primary';

    return (
        <Card className="mb-3">
            <Card.Header className="d-flex align-items-center">
                <FaDollarSign className="me-2 text-primary" />
                <span className="fw-semibold">
                    {t('ai.budgetTitle', 'Monthly AI cost budget')}
                </span>
                {status?.month_start_utc && (
                    <small className="text-muted ms-auto">
                        {formatMonth(status.month_start_utc)} (UTC)
                    </small>
                )}
            </Card.Header>
            <Card.Body>
                {loading ? (
                    <div className="text-center py-3">
                        <Spinner animation="border" size="sm" />
                    </div>
                ) : (
                    <>
                        {/* Gauge */}
                        {budgetNum != null ? (
                            <>
                                <div className="d-flex justify-content-between align-items-baseline mb-1">
                                    <span className="small text-muted">
                                        {t('ai.budgetSpent', 'Spent this month')}
                                    </span>
                                    <span className="fw-semibold">
                                        {formatUsd(spendNum)} <span className="text-muted">/ {formatUsd(budgetNum)}</span>
                                        <Badge bg={barVariant === 'primary' ? 'secondary' : barVariant} className="ms-2">
                                            {pct.toFixed(1)}%
                                        </Badge>
                                    </span>
                                </div>
                                <ProgressBar
                                    now={Math.min(100, pct)}
                                    variant={barVariant}
                                    style={{ height: 8 }}
                                    aria-label={`${pct.toFixed(1)}% of monthly budget used`}
                                />
                                <div className="mt-2">
                                    {status?.is_exceeded ? (
                                        <Alert variant="danger" className="d-flex align-items-start mb-0 py-2 small">
                                            <FaExclamationTriangle className="me-2 mt-1" />
                                            <div>
                                                <strong>{t('ai.budgetExceeded', 'Monthly budget reached.')}</strong>{' '}
                                                {t('ai.budgetPaused', 'AI-driven RCA is paused for the rest of the month. Rule-based issue creation (Sentinel, correlation engine) still runs.')}
                                            </div>
                                        </Alert>
                                    ) : status?.is_warning ? (
                                        <Alert variant="warning" className="d-flex align-items-start mb-0 py-2 small">
                                            <FaExclamationTriangle className="me-2 mt-1" />
                                            {t('ai.budgetWarning', 'Above the warn threshold. Consider raising the cap or reducing analysis frequency.')}
                                        </Alert>
                                    ) : (
                                        <div className="text-muted small">
                                            <FaCheckCircle className="me-1 text-success" />
                                            {t('ai.budgetHealthy', 'Within budget.')}{' '}
                                            {status?.remaining_usd != null && (
                                                <>
                                                    {formatUsd(status.remaining_usd)} {t('ai.budgetRemaining', 'remaining')}.
                                                </>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </>
                        ) : (
                            <Alert variant="secondary" className="d-flex align-items-start mb-0 py-2 small">
                                <FaInfoCircle className="me-2 mt-1" />
                                <div>
                                    <strong>{t('ai.budgetNone', 'No monthly cap set.')}</strong>{' '}
                                    {t('ai.budgetNoneHint', 'AI spend is unlimited. Setting a cap is recommended for cost predictability, especially on hosted providers.')}
                                    {status?.current_spend_usd != null && (
                                        <>
                                            {' '}
                                            <span className="text-muted">
                                                ({t('ai.budgetSpentSoFar', 'Spent so far this month')}: {formatUsd(spendNum)})
                                            </span>
                                        </>
                                    )}
                                </div>
                            </Alert>
                        )}

                        {/* Editable inputs */}
                        <hr className="my-3" />
                        <Form>
                            <div className="row g-3">
                                <div className="col-md-6">
                                    <Form.Label className="small fw-semibold mb-1">
                                        {t('ai.budgetInput', 'Monthly budget (USD)')}
                                    </Form.Label>
                                    <Form.Control
                                        type="number"
                                        step="0.01"
                                        min="0"
                                        placeholder={t('ai.budgetInputPlaceholder', 'Leave blank for unlimited')}
                                        value={budgetInput}
                                        onChange={(e) => setBudgetInput(e.target.value)}
                                        aria-label="Monthly AI budget in USD"
                                    />
                                    <Form.Text className="text-muted">
                                        {t('ai.budgetInputHelp', 'Hard cap on AI API spend per calendar month. Rule-based issue creation continues after the cap.')}
                                    </Form.Text>
                                </div>
                                <div className="col-md-6">
                                    <Form.Label className="small fw-semibold mb-1">
                                        {t('ai.warnPctInput', 'Warn threshold (%)')}
                                    </Form.Label>
                                    <Form.Control
                                        type="number"
                                        min="0"
                                        max="100"
                                        value={warnInput}
                                        onChange={(e) => setWarnInput(e.target.value)}
                                        aria-label="Budget warn threshold percent"
                                    />
                                    <Form.Text className="text-muted">
                                        {t('ai.warnPctHelp', 'Show a warning banner once spend crosses this fraction of the cap. Default 80%.')}
                                    </Form.Text>
                                </div>
                            </div>
                            <div className="d-flex justify-content-end mt-3">
                                <Button
                                    variant="primary"
                                    onClick={handleSave}
                                    disabled={saving}
                                    size="sm"
                                >
                                    {saving ? (
                                        <>
                                            <Spinner size="sm" className="me-2" />
                                            {t('common.saving', 'Saving…')}
                                        </>
                                    ) : (
                                        t('ai.budgetSave', 'Save budget')
                                    )}
                                </Button>
                            </div>
                        </Form>
                    </>
                )}
            </Card.Body>
        </Card>
    );
};

export default AIBudgetCard;

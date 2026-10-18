/**
 * User Notification Preferences Component
 * Configure personal notification preferences (quiet hours, digest, project subscriptions)
 */

import React, { useState, useEffect } from 'react';
import { Form, Button, Spinner, Badge, Card, ListGroup } from 'react-bootstrap';
import {
    FaBell, FaMoon, FaEnvelope, FaClock, FaProjectDiagram,
    FaCheck, FaTimes, FaPlus, FaTrash
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import NotificationService from '../../services/notification.service';
import { ProjectService } from '../../services/project.service';
import CollapsibleSection from './CollapsibleSection';
import './SettingsLayout.css';
import PageHeader from '../PageHeader';

const TIMEZONE_OPTIONS = [
    'UTC', 'America/New_York', 'America/Los_Angeles', 'America/Chicago',
    'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Asia/Tokyo',
    'Asia/Shanghai', 'Australia/Sydney'
];

const DIGEST_OPTION_KEYS = [
    { value: 'immediate', key: 'preferences.delivery.immediate' },
    { value: 'hourly', key: 'preferences.delivery.hourly' },
    { value: 'daily', key: 'preferences.delivery.daily' },
    { value: 'weekly', key: 'preferences.delivery.weekly' }
];

const UserPreferencesSettings = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [preferences, setPreferences] = useState({
        email_enabled: true,
        in_app_enabled: true,
        notify_critical: true,
        notify_warning: true,
        notify_info: false,
        digest_frequency: 'immediate',
        quiet_hours_enabled: false,
        quiet_hours_start: '22:00',
        quiet_hours_end: '08:00',
        timezone: 'UTC'
    });
    const [subscriptions, setSubscriptions] = useState([]);
    const [availableProjects, setAvailableProjects] = useState([]);
    const [selectedProject, setSelectedProject] = useState('');

    useEffect(() => {
        fetchPreferences();
        fetchSubscriptions();
        fetchProjects();
    }, []);

    const fetchPreferences = async () => {
        try {
            const response = await NotificationService.getPreferences();
            setPreferences(response.data);
        } catch (error) {
            console.error('Failed to fetch preferences:', error);
        } finally {
            setLoading(false);
        }
    };

    const fetchSubscriptions = async () => {
        try {
            const response = await NotificationService.getSubscriptions();
            setSubscriptions(response.data);
        } catch (error) {
            console.error('Failed to fetch subscriptions:', error);
        }
    };

    const fetchProjects = async () => {
        try {
            const response = await ProjectService.GetProjects();
            setAvailableProjects(response || []);
        } catch (error) {
            console.error('Failed to fetch projects:', error);
        }
    };

    const handlePreferenceChange = (field, value) => {
        setPreferences(prev => ({ ...prev, [field]: value }));
    };

    const handleSavePreferences = async () => {
        try {
            setSaving(true);
            await NotificationService.updatePreferences(preferences);
            toast.success(t('preferences.saved'));
        } catch (error) {
            toast.error(error.response?.data?.error || t('common.error'));
        } finally {
            setSaving(false);
        }
    };

    const handleSubscribe = async () => {
        if (!selectedProject) return;

        try {
            await NotificationService.subscribeToProject(selectedProject);
            toast.success(t('preferences.subscriptions.subscribed'));
            setSelectedProject('');
            fetchSubscriptions();
        } catch (error) {
            toast.error(error.response?.data?.error || t('preferences.subscriptions.subscribeFailed'));
        }
    };

    const handleUnsubscribe = async (subscriptionId) => {
        try {
            await NotificationService.unsubscribeFromProject(subscriptionId);
            toast.success(t('preferences.subscriptions.unsubscribed'));
            fetchSubscriptions();
        } catch (error) {
            toast.error(t('preferences.subscriptions.unsubscribeFailed'));
        }
    };

    const subscribedProjectIds = subscriptions.map(s => s.project);
    const unsubscribedProjects = availableProjects.filter(
        p => !subscribedProjectIds.includes(p.id)
    );

    if (loading) {
        return (
            <div className="text-center py-5">
                <Spinner animation="border" variant="primary" />
                <p className="mt-3 text-muted">{t('common.loading')}</p>
            </div>
        );
    }

    return (
        <div className="settings-section">
            <PageHeader title={t('preferences.title')} subtitle={t('preferences.subtitle')} />

            {/* Channel Preferences */}
            <CollapsibleSection
                title={t('preferences.channels.title')}
                description={t('preferences.channels.subtitle')}
                defaultExpanded={true}
            >
                <div className="toggle-item large">
                    <div className="toggle-label">
                        <span><FaEnvelope className="me-2" />{t('preferences.channels.email')}</span>
                        <small>{t('preferences.channels.emailHint')}</small>
                    </div>
                    <label className="settings-toggle-switch">
                        <input
                            type="checkbox"
                            checked={preferences.email_enabled}
                            onChange={(e) => handlePreferenceChange('email_enabled', e.target.checked)}
                        />
                        <span className="toggle-slider"></span>
                    </label>
                </div>

                <div className="toggle-item large">
                    <div className="toggle-label">
                        <span><FaBell className="me-2" />{t('preferences.channels.inApp')}</span>
                        <small>{t('preferences.channels.inAppHint')}</small>
                    </div>
                    <label className="settings-toggle-switch">
                        <input
                            type="checkbox"
                            checked={preferences.in_app_enabled}
                            onChange={(e) => handlePreferenceChange('in_app_enabled', e.target.checked)}
                        />
                        <span className="toggle-slider"></span>
                    </label>
                </div>
            </CollapsibleSection>

            {/* Severity Filters */}
            <CollapsibleSection
                title={t('preferences.severity.title')}
                description={t('preferences.severity.subtitle')}
            >
                <div className="toggle-item large">
                    <div className="toggle-label">
                        <span className="text-danger"><FaBell className="me-2" />{t('preferences.severity.critical')}</span>
                        <small>{t('preferences.severity.criticalHint')}</small>
                    </div>
                    <label className="settings-toggle-switch">
                        <input
                            type="checkbox"
                            checked={preferences.notify_critical}
                            onChange={(e) => handlePreferenceChange('notify_critical', e.target.checked)}
                        />
                        <span className="toggle-slider"></span>
                    </label>
                </div>

                <div className="toggle-item large">
                    <div className="toggle-label">
                        <span className="settings-tone-warn"><FaBell className="me-2" />{t('preferences.severity.warnings')}</span>
                        <small>{t('preferences.severity.warningsHint')}</small>
                    </div>
                    <label className="settings-toggle-switch">
                        <input
                            type="checkbox"
                            checked={preferences.notify_warning}
                            onChange={(e) => handlePreferenceChange('notify_warning', e.target.checked)}
                        />
                        <span className="toggle-slider"></span>
                    </label>
                </div>

                <div className="toggle-item large">
                    <div className="toggle-label">
                        <span className="text-info"><FaBell className="me-2" />{t('preferences.severity.info')}</span>
                        <small>{t('preferences.severity.infoHint')}</small>
                    </div>
                    <label className="settings-toggle-switch">
                        <input
                            type="checkbox"
                            checked={preferences.notify_info}
                            onChange={(e) => handlePreferenceChange('notify_info', e.target.checked)}
                        />
                        <span className="toggle-slider"></span>
                    </label>
                </div>
            </CollapsibleSection>

            {/* Digest Settings */}
            <CollapsibleSection
                title={t('preferences.delivery.title')}
                description={t('preferences.delivery.subtitle')}
            >
                <div className="settings-form-panel">
                    <div className="form-group mb-4">
                        <label className="settings-form-label">
                            <FaClock className="me-2" />{t('preferences.delivery.digestFrequency')}
                        </label>
                        <Form.Select
                            value={preferences.digest_frequency}
                            onChange={(e) => handlePreferenceChange('digest_frequency', e.target.value)}
                        >
                            {DIGEST_OPTION_KEYS.map(opt => (
                                <option key={opt.value} value={opt.value}>{t(opt.key)}</option>
                            ))}
                        </Form.Select>
                        <small className="text-muted">
                            {preferences.digest_frequency === 'immediate'
                                ? t('preferences.delivery.immediateHint')
                                : t('preferences.delivery.bundledHint')}
                        </small>
                    </div>
                </div>
            </CollapsibleSection>

            {/* Quiet Hours */}
            <CollapsibleSection
                title={t('preferences.quietHours.title')}
                description={t('preferences.quietHours.subtitle')}
            >
                <div className="toggle-item large mb-4">
                    <div className="toggle-label">
                        <span><FaMoon className="me-2" />{t('preferences.quietHours.enable')}</span>
                        <small>{t('preferences.quietHours.enableHint')}</small>
                    </div>
                    <label className="settings-toggle-switch">
                        <input
                            type="checkbox"
                            checked={preferences.quiet_hours_enabled}
                            onChange={(e) => handlePreferenceChange('quiet_hours_enabled', e.target.checked)}
                        />
                        <span className="toggle-slider"></span>
                    </label>
                </div>

                {preferences.quiet_hours_enabled && (
                    <div className="settings-form-panel">
                        <div className="row">
                            <div className="col-md-4">
                                <div className="form-group">
                                    <label className="settings-form-label">{t('preferences.quietHours.startTime')}</label>
                                    <Form.Control
                                        type="time"
                                        value={preferences.quiet_hours_start || '22:00'}
                                        onChange={(e) => handlePreferenceChange('quiet_hours_start', e.target.value)}
                                    />
                                </div>
                            </div>
                            <div className="col-md-4">
                                <div className="form-group">
                                    <label className="settings-form-label">{t('preferences.quietHours.endTime')}</label>
                                    <Form.Control
                                        type="time"
                                        value={preferences.quiet_hours_end || '08:00'}
                                        onChange={(e) => handlePreferenceChange('quiet_hours_end', e.target.value)}
                                    />
                                </div>
                            </div>
                            <div className="col-md-4">
                                <div className="form-group">
                                    <label className="settings-form-label">{t('preferences.quietHours.timezone')}</label>
                                    <Form.Select
                                        value={preferences.timezone}
                                        onChange={(e) => handlePreferenceChange('timezone', e.target.value)}
                                    >
                                        {TIMEZONE_OPTIONS.map(tz => (
                                            <option key={tz} value={tz}>{tz}</option>
                                        ))}
                                    </Form.Select>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </CollapsibleSection>

            {/* Project Subscriptions */}
            <CollapsibleSection
                title={t('preferences.subscriptions.title')}
                description={t('preferences.subscriptions.subtitle')}
            >
                <div className="settings-form-panel mb-4">
                    <div className="form-group">
                        <label className="settings-form-label">
                            <FaProjectDiagram className="me-2" />{t('preferences.subscriptions.subscribeTo')}
                        </label>
                        <div className="input-group">
                            <Form.Select
                                value={selectedProject}
                                onChange={(e) => setSelectedProject(e.target.value)}
                            >
                                <option value="">{t('preferences.subscriptions.selectProject')}</option>
                                {unsubscribedProjects.map(project => (
                                    <option key={project.id} value={project.id}>
                                        {project.name}
                                    </option>
                                ))}
                            </Form.Select>
                            <Button
                                variant="outline-primary"
                                onClick={handleSubscribe}
                                disabled={!selectedProject}
                            >
                                <FaPlus className="me-1" /> {t('preferences.subscriptions.subscribe')}
                            </Button>
                        </div>
                    </div>
                </div>

                <ListGroup>
                    {subscriptions.length === 0 ? (
                        <ListGroup.Item className="text-muted text-center">
                            {t('preferences.subscriptions.noSubscriptions')}
                        </ListGroup.Item>
                    ) : (
                        subscriptions.map(sub => (
                            <ListGroup.Item
                                key={sub.id}
                                className="d-flex justify-content-between align-items-center"
                            >
                                <div>
                                    <strong>{sub.project_name}</strong>
                                    <div className="mt-1">
                                        {sub.notify_critical && (
                                            <Badge bg="danger" className="me-1">Critical</Badge>
                                        )}
                                        {sub.notify_warning && (
                                            <Badge bg="warning" className="me-1">Warning</Badge>
                                        )}
                                        {sub.notify_info && (
                                            <Badge bg="info">Info</Badge>
                                        )}
                                    </div>
                                </div>
                                <Button
                                    variant="outline-danger"
                                    size="sm"
                                    onClick={() => handleUnsubscribe(sub.id)}
                                >
                                    <FaTrash />
                                </Button>
                            </ListGroup.Item>
                        ))
                    )}
                </ListGroup>
            </CollapsibleSection>

            <div className="settings-page-actions">
                <button
                    className="btn btn-primary"
                    onClick={handleSavePreferences}
                    disabled={saving}
                >
                    {saving ? t('common.saving') : t('preferences.save')}
                </button>
            </div>
        </div>
    );
};

export default UserPreferencesSettings;

import React, { useState, useEffect, useCallback } from "react";
import { Bell, CheckCheck, CircleCheck, Mail, MailOpen, Trash2, TriangleAlert, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import NotificationService from "../services/notification.service";
import PageHeader from './PageHeader';
import './NotificationPanel.css';

const noop = () => {};

// variant="popover" is the bell dropdown; variant="page" is /dash/notifications
// (linked from the digest email), where there is nothing to close and no badge
// to keep in sync.
const NotificationPanel = ({ onClose = noop, unreadCount, setUnreadCount = noop, variant = 'popover' }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionNotice, setActionNotice] = useState(null);
  // The page variant has no parent badge, so the panel keeps its own count.
  const [ownUnread, setOwnUnread] = useState(unreadCount ?? 0);
  const updateUnread = useCallback((n) => { setOwnUnread(n); setUnreadCount(n); }, [setUnreadCount]);
  const shownUnread = unreadCount ?? ownUnread;

  // Surface backend refusal (403 demo_read_only) as a friendly banner
  // rather than a silent no-op. Any other axios error is logged and
  // shown as a generic "action failed" so the user knows the click
  // registered but did not succeed.
  const handleActionError = (err, fallback) => {
    const data = err?.response?.data;
    if (data?.error === 'demo_read_only') {
      setActionNotice({
        kind: 'demo',
        text: data.message || t('notifications.panel.demoReadOnly'),
      });
      return;
    }
    console.error(fallback, err);
    setActionNotice({
      kind: 'error',
      text: t('notifications.panel.actionFailed'),
    });
  };

  useEffect(() => {
    const fetchNotifications = async () => {
      try {
        let response;
        if (filter === 'all') {
          response = await NotificationService.getAllNotifications();
        } else if (filter === 'read') {
          response = await NotificationService.getReadNotifications();
        } else {
          response = await NotificationService.getAllNotifications({ is_read: false });
        }

        setNotifications(response.data);
        setLoading(false);

        // Update unread count
        const unreadResponse = await NotificationService.getUnreadCount();
        updateUnread(unreadResponse.data.unread_count);
      } catch (err) {
        setError(err.message);
        setLoading(false);
      }
    };

    fetchNotifications();
  }, [filter, updateUnread]);

  const markAsRead = async (id) => {
    try {
      await NotificationService.markAsRead(id);
      setNotifications(notifications.map(note =>
        note.id === id ? { ...note, is_read: true } : note
      ));

      // Update unread count
      const response = await NotificationService.getUnreadCount();
      updateUnread(response.data.unread_count);
    } catch (err) {
      handleActionError(err, 'Error marking as read:');
    }
  };

  const markAsUnread = async (id) => {
    try {
      await NotificationService.markAsUnread(id);
      setNotifications(notifications.map(note =>
        note.id === id ? { ...note, is_read: false } : note
      ));

      // Update unread count
      const response = await NotificationService.getUnreadCount();
      updateUnread(response.data.unread_count);
    } catch (err) {
      handleActionError(err, 'Error marking as unread:');
    }
  };

  const removeNotification = async (id) => {
    try {
      await NotificationService.deleteNotification(id);
      setNotifications(notifications.filter(note => note.id !== id));

      // Update unread count if needed
      const response = await NotificationService.getUnreadCount();
      updateUnread(response.data.unread_count);
    } catch (err) {
      handleActionError(err, 'Error deleting notification:');
    }
  };

  // Preserve legacy "close per-item" semantics for non-demo callers by
  // using the backend's dedicated bulk endpoint. Fanning out N delete
  // requests here was both slow and half-broken under demo_read_only
  // (some would fire, most would 403, the client state got confused).
  const removeAllNotifications = async () => {
    try {
      await NotificationService.deleteAllNotifications();
      setNotifications([]);
      updateUnread(0);
    } catch (err) {
      handleActionError(err, 'Error deleting all notifications:');
    }
  };

  const markAllAsRead = async () => {
    try {
      await NotificationService.markAllAsRead();
      setNotifications(notifications.map(note => ({ ...note, is_read: true })));
      updateUnread(0);
    } catch (err) {
      handleActionError(err, 'Error marking all as read:');
    }
  };

  const toggleReadStatus = async (id, isRead) => {
    if (isRead) {
      await markAsUnread(id);
    } else {
      await markAsRead(id);
    }
  };

  const formatTime = (dateString) => {
    const now = new Date();
    const date = new Date(dateString);
    const diffInSeconds = Math.floor((now - date) / 1000);

    if (diffInSeconds < 60) return t('notifications.panel.time.now');
    if (diffInSeconds < 3600) return t('notifications.panel.time.minutes', { count: Math.floor(diffInSeconds / 60) });
    if (diffInSeconds < 86400) return t('notifications.panel.time.hours', { count: Math.floor(diffInSeconds / 3600) });
    if (diffInSeconds < 604800) return t('notifications.panel.time.days', { count: Math.floor(diffInSeconds / 86400) });
    return date.toLocaleDateString();
  };

  const filteredNotifications = notifications.filter(note => {
    if (filter === 'all') return true;
    if (filter === 'unread') return !note.is_read;
    if (filter === 'read') return note.is_read;
    return true;
  });

  // One tone per kind, from the design tokens (works in both themes).
  const getTone = (type) => {
    if (type === 'critical_issue') return 'err';
    if (type === 'analysis_failed') return 'warn';
    if (type === 'investigation_done') return 'ok';
    return 'neutral';
  };

  const getCategoryName = (type) => {
    const key = `notifications.panel.types.${type}`;
    return t(key, { defaultValue: t('notifications.panel.types.default') });
  };

  const handleNotificationClick = async (notification) => {
    if (!notification.is_read) {
      await markAsRead(notification.id);
    }

    // Close panel
    onClose();

    switch (notification.notification_type) {
      case 'critical_issue':
        if (notification.batch_id) {
          navigate(`/dash/issues/${notification.batch_id}`);
        }
        break;
      case 'investigation_done':
        navigate(notification.batch_id ? `/dash/data/details/${notification.batch_id}` : '/dash/investigate');
        break;
      default:
        break;
    }
  };

  const isPage = variant === 'page';
  const shell = (children) => (
    <motion.div
      initial={{ opacity: 0, y: isPage ? 0 : -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.15 }}
      className={`notification-panel-overlay${isPage ? ' is-page' : ''}`}
    >
      {children}
    </motion.div>
  );

  const unreadLine = t('notifications.panel.unread', { total: shownUnread });
  const header = isPage ? (
    <PageHeader title={t('notifications.panel.title')} subtitle={unreadLine} />
  ) : (
    <div className="notification-header">
      <div>
        <h3 className="notification-title">{t('notifications.panel.title')}</h3>
        <p className="notification-subtitle">{unreadLine}</p>
      </div>
      <button onClick={onClose} className="notification-close-btn" aria-label={t('common.close')}>
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );

  if (loading || error) {
    return shell(
      <>
        {header}
        <div className={`notification-card notification-state${error ? ' is-error' : ''}`}>
          {error ? t('notifications.panel.error', { message: error }) : t('notifications.panel.loading')}
        </div>
      </>
    );
  }

  const filters = [
    { value: 'all', label: t('notifications.panel.tabs.all') },
    { value: 'unread', label: t('notifications.panel.tabs.unread') },
    { value: 'read', label: t('notifications.panel.tabs.read') },
  ];

  return shell(
    <>
      {header}

      {/* Surfaces a backend refusal (demo read-only) or a failed action,
          so a click never silently does nothing. */}
      {actionNotice && (
        <div
          className={`notification-action-notice notification-action-notice--${actionNotice.kind}`}
          role="status"
        >
          <span>{actionNotice.text}</span>
          <button
            type="button"
            onClick={() => setActionNotice(null)}
            className="notification-action-notice__close"
            aria-label={t('common.close')}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      )}

      <div className="notification-card">
        <div className="notification-filter-bar">
          <div className="ds-segmented" role="tablist" aria-label={t('notifications.panel.title')}>
            {filters.map((f) => (
              <button
                key={f.value}
                type="button"
                role="tab"
                aria-selected={filter === f.value}
                className={`ds-choice-option ${filter === f.value ? 'is-checked' : ''}`}
                onClick={() => setFilter(f.value)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="notification-bulk">
            <button
              type="button"
              onClick={markAllAsRead}
              disabled={shownUnread === 0}
              className="btn btn-sm ds-btn-ghost"
            >
              <CheckCheck size={14} aria-hidden="true" /> {t('notifications.panel.markAllRead')}
            </button>
            {notifications.length > 0 && (
              <button type="button" onClick={removeAllNotifications} className="btn btn-sm ds-btn-ghost">
                <Trash2 size={14} aria-hidden="true" /> {t('notifications.panel.clearAll')}
              </button>
            )}
          </div>
        </div>

        <ul className="notification-list">
          <AnimatePresence initial={false}>
            {filteredNotifications.length > 0 ? (
              filteredNotifications.map((note) => {
                const tone = getTone(note.notification_type);
                const Icon = tone === 'err' || tone === 'warn' ? TriangleAlert : tone === 'ok' ? CircleCheck : Bell;
                return (
                  <motion.li
                    key={note.id}
                    layout
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.15 }}
                    className={`notification-item ${!note.is_read ? 'unread' : ''}`}
                  >
                    <span className={`notification-item-icon tone-${tone}`} aria-hidden="true">
                      <Icon size={16} />
                    </span>
                    <button
                      type="button"
                      className="notification-item-content"
                      onClick={() => handleNotificationClick(note)}
                    >
                      <span className="notification-item-title">
                        {!note.is_read && <span className="notification-unread-dot" aria-label={t('notifications.panel.tabs.unread')} />}
                        {note.subject}
                      </span>
                      <span className="notification-item-message">{note.message}</span>
                      <span className="notification-item-footer">
                        <span className="notification-time">{formatTime(note.created_at)}</span>
                        {tone !== 'neutral' && (
                          <span className={`badge ds-chip ds-chip-${tone}`}>{getCategoryName(note.notification_type)}</span>
                        )}
                      </span>
                    </button>
                    <div className="notification-item-actions">
                      <button
                        type="button"
                        onClick={() => toggleReadStatus(note.id, note.is_read)}
                        className="notification-icon-btn"
                        title={note.is_read ? t('notifications.panel.tooltips.markUnread') : t('notifications.panel.tooltips.markRead')}
                        aria-label={note.is_read ? t('notifications.panel.tooltips.markUnread') : t('notifications.panel.tooltips.markRead')}
                      >
                        {note.is_read ? <MailOpen size={15} aria-hidden="true" /> : <Mail size={15} aria-hidden="true" />}
                      </button>
                      <button
                        type="button"
                        onClick={() => removeNotification(note.id)}
                        className="notification-icon-btn"
                        title={t('notifications.panel.tooltips.delete')}
                        aria-label={t('notifications.panel.tooltips.delete')}
                      >
                        <X size={15} aria-hidden="true" />
                      </button>
                    </div>
                  </motion.li>
                );
              })
            ) : (
              <li className="notification-empty">
                <Bell size={28} aria-hidden="true" />
                <p className="notification-empty-title">{t('notifications.panel.empty.title')}</p>
                <p className="notification-empty-sub">
                  {filter === 'all'
                    ? t('notifications.panel.empty.all')
                    : filter === 'read'
                      ? t('notifications.panel.empty.read')
                      : t('notifications.panel.empty.unread')}
                </p>
              </li>
            )}
          </AnimatePresence>
        </ul>
      </div>
    </>
  );
};

export default NotificationPanel;
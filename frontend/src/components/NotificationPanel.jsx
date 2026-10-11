import React, { useState, useEffect } from "react";
import { FaBell, FaBullhorn, FaEye, FaEyeSlash, FaTimes, FaExclamationTriangle, FaTrash } from 'react-icons/fa';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import NotificationService from "../services/notification.service";
import './NotificationPanel.css';

const NotificationPanel = ({ onClose, unreadCount, setUnreadCount }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [actionNotice, setActionNotice] = useState(null);

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
        setUnreadCount(unreadResponse.data.unread_count);
      } catch (err) {
        setError(err.message);
        setLoading(false);
      }
    };

    fetchNotifications();
  }, [filter, setUnreadCount]);

  const markAsRead = async (id) => {
    try {
      await NotificationService.markAsRead(id);
      setNotifications(notifications.map(note =>
        note.id === id ? { ...note, is_read: true } : note
      ));

      // Update unread count
      const response = await NotificationService.getUnreadCount();
      setUnreadCount(response.data.unread_count);
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
      setUnreadCount(response.data.unread_count);
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
      setUnreadCount(response.data.unread_count);
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
      setUnreadCount(0);
    } catch (err) {
      handleActionError(err, 'Error deleting all notifications:');
    }
  };

  const markAllAsRead = async () => {
    try {
      await NotificationService.markAllAsRead();
      setNotifications(notifications.map(note => ({ ...note, is_read: true })));
      setUnreadCount(0);
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

  const getPriorityForType = (type) => {
    switch (type) {
      case 'critical_issue': return 'high';
      case 'analysis_failed': return 'high';
      default: return 'normal';
    }
  };

  const getIconForType = (type) => {
    switch (type) {
      case 'critical_issue': return <FaExclamationTriangle />;
      case 'analysis_failed': return <FaExclamationTriangle />;
      default: return <FaBullhorn />;
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

  const getCategoryColor = (category) => {
    const colors = {
      'critical_issue': '#ff4d4f',
      'analysis_failed': '#faad14'
    };
    return colors[category] || '#1890ff';
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
      default:
        break;
    }
  };

  if (loading) {
    return (
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -20 }}
        transition={{ duration: 0.3 }}
        className="notification-panel-overlay"
      >
        <div style={{ padding: '2rem', textAlign: 'center' }}>
          {t('notifications.panel.loading')}
        </div>
      </motion.div>
    );
  }

  if (error) {
    return (
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -20 }}
        transition={{ duration: 0.3 }}
        className="notification-panel-overlay"
      >
        <div style={{ padding: '2rem', textAlign: 'center', color: '#ff4d4f' }}>
          {t('notifications.panel.error', { message: error })}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3 }}
      className="notification-panel-overlay"
    >
      {/* Header */}
      <div className="notification-header">
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <div className="notification-icon-wrapper">
            <FaBell />
          </div>
          <div>
            <h3 className="notification-title">{t('notifications.panel.title')}</h3>
            <p className="notification-subtitle">
              <span className="notification-dot"></span>
              {t('notifications.panel.unread', { total: unreadCount })}
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="notification-close-btn"
        >
          <FaTimes />
        </button>
      </div>

      {/* Action notice — surfaces backend refusal (demo read-only) or
          a generic action failure so a click never silently no-ops. */}
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
            <FaTimes />
          </button>
        </div>
      )}

      {/* Filter Bar */}
      <div className="notification-filter-bar">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => setFilter('all')}
              className={`notification-filter-btn ${filter === 'all' ? 'active' : ''}`}
            >
              <FaEye style={{ marginRight: '6px' }} /> {t('notifications.panel.tabs.all')}
            </button>
            <button
              onClick={() => setFilter('unread')}
              className={`notification-filter-btn ${filter === 'unread' ? 'active' : ''}`}
            >
              {t('notifications.panel.tabs.unread')}
            </button>
            <button
              onClick={() => setFilter('read')}
              className={`notification-filter-btn ${filter === 'read' ? 'active' : ''}`}
            >
              {t('notifications.panel.tabs.read')}
            </button>
          </div>

          <div style={{ display: 'flex', gap: '12px' }}>
            <button
              onClick={markAllAsRead}
              disabled={unreadCount === 0}
              className="notification-action-btn"
            >
              {t('notifications.panel.markAllRead')}
            </button>

            {notifications.length > 0 && (
              <button
                onClick={removeAllNotifications}
                className="notification-action-btn"
                style={{ ':hover': { color: '#ff4d4f' } }}
              >
                <FaTrash style={{ marginRight: '4px' }} /> {t('notifications.panel.clearAll')}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Notifications List */}
      <div className="notification-list">
        <AnimatePresence>
          {filteredNotifications.length > 0 ? (
            filteredNotifications.map((note) => (
              <motion.div
                key={note.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -50 }}
                transition={{ duration: 0.2 }}
                className={`notification-item ${!note.is_read ? 'unread' : ''}`}
                onClick={() => handleNotificationClick(note)}
              >
                {/* Unread indicator */}
                {!note.is_read && (
                  <div style={{
                    position: 'absolute',
                    right: '12px',
                    top: '24px',
                    width: '8px',
                    height: '8px',
                    backgroundColor: getCategoryColor(note.notification_type),
                    borderRadius: '50%'
                  }} />
                )}

                {/* Icon */}
                <div className="notification-item-icon" style={{
                  color: getCategoryColor(note.notification_type),
                  backgroundColor: !note.is_read ? '#e6f7ff' : '#f5f5f5',
                }}>
                  {getIconForType(note.notification_type)}
                </div>

                {/* Content */}
                <div className="notification-item-content">
                  <div className="notification-item-header">
                    <div>
                      <h4 className="notification-item-title">
                        {note.subject}
                      </h4>
                      <p className="notification-item-message">
                        {note.message}
                      </p>
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleReadStatus(note.id, note.is_read);
                        }}
                        className="notification-action-btn"
                        title={note.is_read ? t('notifications.panel.tooltips.markUnread') : t('notifications.panel.tooltips.markRead')}
                      >
                        {note.is_read ? <FaEyeSlash /> : <FaEye />}
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          removeNotification(note.id);
                        }}
                        className="notification-action-btn"
                        style={{ ':hover': { color: '#ff4d4f' } }}
                        title={t('notifications.panel.tooltips.delete')}
                      >
                        <FaTimes />
                      </button>
                    </div>
                  </div>

                  <div className="notification-item-footer">
                    <span className="notification-time">
                      {formatTime(note.created_at)}
                    </span>
                    <span
                      className="notification-badge"
                      style={{ backgroundColor: getCategoryColor(note.notification_type) }}
                    >
                      {getCategoryName(note.notification_type)}
                    </span>
                  </div>
                </div>
              </motion.div>
            ))
          ) : (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: '200px',
                color: '#bfbfbf'
              }}
            >
              <FaBell style={{ fontSize: '2.5rem', marginBottom: '1rem' }} />
              <p style={{ margin: 0, fontWeight: 500 }}>{t('notifications.panel.empty.title')}</p>
              <p style={{ margin: 0, fontSize: '0.875rem' }}>
                {filter === 'all'
                  ? t('notifications.panel.empty.all')
                  : filter === 'read'
                    ? t('notifications.panel.empty.read')
                    : t('notifications.panel.empty.unread')}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
};

export default NotificationPanel;
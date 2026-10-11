import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_BASE_URL || 'http://127.0.0.1:8000/api';

class NotificationService {
  constructor() {
    this.api = axios.create({
      baseURL: `${API_BASE_URL}/notification/`,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }

  _getAuthHeaders() {
    const token = localStorage.getItem('token');
    return {
      'Authorization': `Token ${token}`
    };
  }

  getAllNotifications(params = {}) {
    return this.api.get('noti/', {
      params,
      headers: this._getAuthHeaders()
    });
  }

  getReadNotifications() {
    return this.api.get('notifications/read/', {
      headers: this._getAuthHeaders()
    });
  }

  getNotification(id) {
    return this.api.get(`${id}/`, {
      headers: this._getAuthHeaders()
    });
  }

  markAsRead(id) {
    return this.api.patch(`${id}/`, { is_read: true }, {
      headers: this._getAuthHeaders()
    });
  }

  markAsUnread(id) {
    return this.api.patch(`${id}/`, { is_read: false }, {
      headers: this._getAuthHeaders()
    });
  }

  markAllAsRead() {
    return this.api.put('mark-all-as-read/', {}, {
      headers: this._getAuthHeaders()
    });
  }

  getUnreadCount() {
    return this.api.get('unread-count/', {
      headers: this._getAuthHeaders()
    });
  }

  deleteNotification(id) {
    return this.api.delete(`${id}/`, {
      headers: this._getAuthHeaders()
    });
  }

  deleteAllNotifications() {
    return this.api.delete('notifications/delete-all/', {
      headers: this._getAuthHeaders()
    });
  }

  // === USER NOTIFICATION PREFERENCES ===

  /**
   * Get current user's notification preferences
   */
  getPreferences() {
    return this.api.get('preferences/', {
      headers: this._getAuthHeaders()
    });
  }

  /**
   * Update current user's notification preferences
   */
  updatePreferences(data) {
    return this.api.put('preferences/', data, {
      headers: this._getAuthHeaders()
    });
  }

  // === PROJECT SUBSCRIPTIONS ===

  /**
   * Get all project subscriptions for current user
   */
  getSubscriptions() {
    return this.api.get('subscriptions/', {
      headers: this._getAuthHeaders()
    });
  }

  /**
   * Subscribe to a project
   */
  subscribeToProject(projectId, options = {}) {
    return this.api.post('subscriptions/', {
      project: projectId,
      notify_critical: options.notify_critical ?? true,
      notify_warning: options.notify_warning ?? true,
      notify_info: options.notify_info ?? false,
    }, {
      headers: this._getAuthHeaders()
    });
  }

  /**
   * Update a subscription
   */
  updateSubscription(subscriptionId, data) {
    return this.api.patch(`subscriptions/${subscriptionId}/`, data, {
      headers: this._getAuthHeaders()
    });
  }

  /**
   * Unsubscribe from a project
   */
  unsubscribeFromProject(subscriptionId) {
    return this.api.delete(`subscriptions/${subscriptionId}/`, {
      headers: this._getAuthHeaders()
    });
  }

  // === ISSUE ACKNOWLEDGMENT ===

  /**
   * Acknowledge an issue to stop escalation
   */
  acknowledgeIssue(issueId) {
    return this.api.post(`issues/${issueId}/acknowledge/`, {}, {
      headers: this._getAuthHeaders()
    });
  }
}

export default new NotificationService();
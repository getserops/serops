---
seo_title: "Notifications and escalation"
description: "Configure SerOps notifications: preferences, project subscriptions and escalation rules so critical issues reach the right person."
---
# Notification System

SerOps provides a comprehensive notification system designed to keep you informed about critical issues without overwhelming your inbox. This guide explains how to configure your preferences, manage subscriptions, and understand internal escalation rules.

## Notification Lifecycle

```mermaid
graph TD
    T[Issue Detected] --> QH{Quiet Hours?}
    QH -->|No| SEV{Severity Filter}
    QH -->|Yes| HOLD[Hold for Summary]
    HOLD --> QE[Quiet Hours End] --> DIGEST[Deliver Summary]
    SEV -->|Matches Preference| CH{Digest Mode?}
    SEV -->|Filtered Out| DROP[No Notification]
    CH -->|Immediate| SEND[Send Now]
    CH -->|Hourly/Daily/Weekly| BATCH[Queue for Digest]
    SEND --> CHAN{Channel}
    CHAN --> EMAIL[Email]
    CHAN --> SLACK[Slack]
    CHAN --> TEAMS[Teams]
    CHAN --> INAPP[In-App]
    SEND --> ACK{Resolved/Muted?}
    ACK -->|No, 15 min| ESC1[Escalation L1<br/>Project Admins]
    ACK -->|No, 45 min| ESC2[Escalation L2<br/>All Org Admins]
    ACK -->|Yes| STOP[Stop Escalation]
```

---

## User Preferences

Each user can fully customize how and when they receive notifications. Access your settings via **User Avatar dropdown > Notifications**.

### Channels
- **Email**: Receive alerts via your registered email address.
- **In-App**: See notifications in the SerOps dashboard bell icon.
- **Slack**: Receive alerts via Slack webhook integration.
- **Microsoft Teams**: Receive alerts via Teams webhook integration.

!!! note "Personal versus organisation-wide"
    The preferences on this page control *your* delivery. The Slack and
    Teams destinations themselves are organisation-wide and configured
    by an admin under **Alerts & routing → Delivery Channels**, with
    **Alerts & routing → Routing Rules** deciding which incidents reach them.
    See [Notifications](../admin/notifications.md).

### Severity Filters
You can choose which types of issues trigger a notification:
- **Critical** (Default: ON): Service-impacting outages or failures.
- **Warning** (Default: ON): Performance degradation or potential risks.
- **Info** (Default: OFF): General system updates and logs.

### Quiet Hours
To prevent burnout, you can configure **Quiet Hours**:
- Notifications generated during this window are **suppressed** (held back).
- They will be delivered as a summary items once your quiet hours end.
- You can set your specific Timezone.

---

## Batched Digests

Instead of receiving an email for every single event, you can opt for **Digests**:
- **Immediate**: Receive alerts as they happen (all Critical issues are always Immediate by default unless Quiet Hours apply).
- **Hourly/Daily/Weekly**: Receive a single email summary of all non-critical events.

Digest emails include:
- Summary statistics (X Critical, Y Warning)
- List of affected projects
- Direct links to the dashboard

---

## Project Subscriptions

SerOps uses an **Auto-Subscribe** model to ensure safety:
1.  **New Users**: Automatically subscribed to all projects they have access to.
2.  **Management**: You can **Unsubscribe** from specific projects you are not actively monitoring.
3.  **Optimization**: Unsubscribing stops all notifications (Critical & Warning) for that specific project.

To manage subscriptions:
- Go to **Notification Preferences > Project Subscriptions**.
- Use the "Subscribe to Project" dropdown to re-subscribe.
- Click the **Trash Icon** to unsubscribe.

---

## Escalation Rules (Automated)

For **Critical Issues** that are not acknowledged, SerOps enforces an automatic escalation policy to ensure coverage.

### Hierarchy
Escalation follows a role-based path:
1.  **Level 1 (15 min)**: Notifies **Project Admins** (Admins who are members of the affected project).
2.  **Level 2 (45 min)**: Notifies **All Organization Admins** (Safety net for the entire org).

### Stopping Escalation
Escalation is an automated backend process. To stop escalation, resolve or mute the issue:
1.  Click "View Issue" in the email or dashboard notification.
2.  Resolve or mute the issue from the issue detail page.
3.  This stops further escalation notifications to your team.

---

## Unsubscribe Links
All email notifications include a direct `Manage Preferences | Unsubscribe` link in the footer, allowing you to quickly tune your settings if an alerting source becomes too noisy.

---

## Related Pages

- [Issues](issues.md) — Issues that trigger notifications
- [Configure Quiet Hours](../how-to/quiet-hours.md) — Step-by-step quiet hours setup
- [Set Up Escalation Rules](../how-to/escalation-rules.md) — Configure escalation tiers
- [Admin Notifications](../admin/notifications.md) — Organisation-wide notification settings
- [Notifications API](../api/notifications.md) — REST API reference

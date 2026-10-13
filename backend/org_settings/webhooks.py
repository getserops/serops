"""
Webhook utilities for Slack and MS Teams notifications.
"""

import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def send_slack_webhook(webhook_url, message_data):
    """
    Send a message to Slack via incoming webhook.
    
    Args:
        webhook_url: Slack incoming webhook URL
        message_data: Dict with Slack message payload
        
    Returns:
        tuple: (success: bool, error: str or None)
    """
    if not webhook_url:
        return False, "Webhook URL not configured"
    
    try:
        response = requests.post(
            webhook_url,
            json=message_data,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"Slack webhook sent successfully")
            return True, None
        else:
            error_msg = f"Slack webhook failed: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, error_msg
            
    except requests.exceptions.Timeout:
        error_msg = "Slack webhook timeout"
        logger.error(error_msg)
        return False, error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Slack webhook error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def send_teams_webhook(webhook_url, message_data):
    """
    Send a message to MS Teams via incoming webhook.
    
    Args:
        webhook_url: MS Teams incoming webhook URL
        message_data: Dict with Teams MessageCard payload
        
    Returns:
        tuple: (success: bool, error: str or None)
    """
    if not webhook_url:
        return False, "Webhook URL not configured"
    
    try:
        response = requests.post(
            webhook_url,
            json=message_data,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        # Teams returns "1" on success
        if response.status_code == 200:
            logger.info(f"Teams webhook sent successfully")
            return True, None
        else:
            error_msg = f"Teams webhook failed: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, error_msg
            
    except requests.exceptions.Timeout:
        error_msg = "Teams webhook timeout"
        logger.error(error_msg)
        return False, error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Teams webhook error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def format_slack_alert(batch_id, issues_count, severity, dashboard_url):
    """
    Format a Slack message for critical issue alerts.
    
    Args:
        batch_id: The batch identifier
        issues_count: Number of issues detected
        severity: Issue severity (critical, warning)
        dashboard_url: URL to view issues
        
    Returns:
        dict: Slack Block Kit message payload
    """
    emoji = "🚨" if severity == "critical" else "⚠️"
    color = "#FF0000" if severity == "critical" else "#FFA500"
    
    return {
        "attachments": [{
            "color": color,
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} {severity.upper()} ALERT",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Batch:*\n{batch_id}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Issues:*\n{issues_count} {severity}"
                        }
                    ]
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "View Issues",
                                "emoji": True
                            },
                            "url": dashboard_url,
                            "style": "danger" if severity == "critical" else "primary"
                        }
                    ]
                }
            ]
        }]
    }


def format_teams_alert(batch_id, issues_count, severity, dashboard_url):
    """
    Format a MS Teams message for critical issue alerts.
    
    Args:
        batch_id: The batch identifier
        issues_count: Number of issues detected
        severity: Issue severity (critical, warning)
        dashboard_url: URL to view issues
        
    Returns:
        dict: MS Teams MessageCard payload
    """
    emoji = "🚨" if severity == "critical" else "⚠️"
    color = "FF0000" if severity == "critical" else "FFA500"
    
    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": f"{severity.upper()} ALERT: {issues_count} issues in {batch_id}",
        "title": f"{emoji} {severity.upper()} ALERT",
        "sections": [{
            "activityTitle": f"**{issues_count} {severity} issues detected**",
            "facts": [
                {
                    "name": "Batch ID",
                    "value": batch_id
                },
                {
                    "name": "Severity",
                    "value": severity.upper()
                },
                {
                    "name": "Issues Count",
                    "value": str(issues_count)
                }
            ],
            "markdown": True
        }],
        "potentialAction": [{
            "@type": "OpenUri",
            "name": "View Issues",
            "targets": [{
                "os": "default",
                "uri": dashboard_url
            }]
        }]
    }


def send_test_slack_webhook(webhook_url):
    """Send a test message to verify Slack webhook configuration."""
    test_message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "✅ *SerOps Slack Integration Test*\n\nYour Slack webhook is configured correctly!"
                }
            }
        ]
    }
    return send_slack_webhook(webhook_url, test_message)


def send_test_teams_webhook(webhook_url):
    """Send a test message to verify MS Teams webhook configuration."""
    test_message = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "00FF00",
        "summary": "SerOps Integration Test",
        "title": "✅ SerOps Teams Integration Test",
        "text": "Your Microsoft Teams webhook is configured correctly!"
    }
    return send_teams_webhook(webhook_url, test_message)

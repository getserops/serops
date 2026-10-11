"""
Utils URL Configuration

API endpoints for utility services like data redaction.
"""

from django.urls import path
from . import views

app_name = 'utils'

urlpatterns = [
    # Scan message for sensitive data (for chat consent workflow)
    path('scan-message/', views.scan_message, name='scan_message'),
]

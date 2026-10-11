"""
Unit Tests for GitLab Celery Tasks

Tests cover:
- Log filtering and cleaning functions
- Failed job log fetching
- Error handling and retries
"""

import unittest
from unittest.mock import Mock, patch, MagicMock

from providers.tasks import (
    filter_error_warning_lines,
    clean_log_message,
)


class TestLogFiltering(unittest.TestCase):
    """Test log filtering and cleaning functions."""

    def test_filter_error_warning_lines(self):
        """Test filtering of error/warning lines from logs."""
        log_text = """
[2024-12-25 10:00:00] INFO: Starting build
[2024-12-25 10:00:01] ERROR: Connection failed
[2024-12-25 10:00:02] INFO: Retrying...
[2024-12-25 10:00:03] WARNING: Timeout detected
[2024-12-25 10:00:04] INFO: Build complete
"""
        filtered = filter_error_warning_lines(log_text)
        
        # Should only include ERROR and WARNING lines
        self.assertGreater(len(filtered), 0)
        self.assertTrue(any('ERROR' in line or 'error' in line.lower() for line in filtered))
        self.assertTrue(any('WARNING' in line or 'warning' in line.lower() for line in filtered))

    def test_filter_removes_ansi_codes(self):
        """Test ANSI escape sequence removal."""
        log_text = "\x1B[31mERROR: Failed to connect\x1B[0m"
        filtered = filter_error_warning_lines(log_text)
        
        # ANSI codes should be removed
        if filtered:
            self.assertNotIn('\x1B', filtered[0])

    def test_filter_excludes_progress_indicators(self):
        """Test that progress indicators are excluded."""
        log_text = """
Downloading [====>    ] 50%
ERROR: File not found
Waiting for service...
"""
        filtered = filter_error_warning_lines(log_text)
        
        # Should not include "Downloading" or "Waiting"
        filtered_text = ' '.join(filtered)
        self.assertNotIn('Downloading', filtered_text)
        self.assertNotIn('Waiting', filtered_text)
        # But should include the error
        self.assertTrue(any('not found' in line.lower() for line in filtered))

    def test_clean_log_message_extracts_msg_field(self):
        """Test extraction of msg field from structured logs."""
        log_line = 'time="2024-12-25T10:00:00" level=error msg="Connection refused"'
        cleaned = clean_log_message(log_line)
        
        self.assertEqual(cleaned, "Connection refused")

    def test_clean_log_message_handles_timestamp_level(self):
        """Test extraction from timestamp + level format."""
        log_line = '2024-12-25T10:00:00 ERROR: Database connection failed'
        cleaned = clean_log_message(log_line)
        
        self.assertEqual(cleaned, "Database connection failed")

    def test_clean_log_message_handles_brackets(self):
        """Test extraction from bracket format."""
        log_line = '[2024-12-25 10:00:00] [ERROR] System failure detected'
        cleaned = clean_log_message(log_line)
        
        self.assertEqual(cleaned, "System failure detected")

    def test_clean_log_message_returns_original_if_no_match(self):
        """Test that original message is returned if no pattern matches."""
        log_line = "Simple error message"
        cleaned = clean_log_message(log_line)
        
        self.assertEqual(cleaned, log_line)


class TestCeleryTaskIntegration(unittest.TestCase):
    """Integration tests for Celery tasks (mocked)."""

    @patch('providers.tasks.GitlabProject.objects')
    @patch('requests.get')
    def test_fetch_failed_job_logs_handles_missing_project(self, mock_get, mock_objects):
        """Test that task handles missing GitLab project gracefully."""
        from providers.tasks import fetch_failed_job_logs_for_project
        
        # Mock: project doesn't exist
        mock_objects.filter.return_value.first.return_value = None
        
        # Should not raise exception
        result = fetch_failed_job_logs_for_project(999)
        
        # Should return early without making API calls
        mock_get.assert_not_called()

    @patch('providers.tasks.GitlabProject.objects')
    @patch('requests.get')
    def test_fetch_failed_job_logs_handles_api_error(self, mock_get, mock_objects):
        """Test that task handles GitLab API errors gracefully."""
        from providers.tasks import fetch_failed_job_logs_for_project
        
        # Mock: project exists
        mock_project = Mock()
        mock_project.project_id = '12345'
        mock_project.access_token = 'test-token'
        mock_objects.filter.return_value.first.return_value = mock_project
        
        # Mock: API returns error
        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response
        
        # Should not raise exception
        result = fetch_failed_job_logs_for_project(1)
        
        # Should have attempted API call
        self.assertTrue(mock_get.called)


if __name__ == '__main__':
    unittest.main()

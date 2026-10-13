"""
Data Tasks Module

TEMPORARY: This module structure is being set up for gradual refactoring.
Currently re-imports from the main tasks.py file for backwards compatibility.

Usage:
    from Data.tasks import create_log_batch, create_batches_for_all_projects
"""

# Import from parent directory's tasks.py
# Celery will autodiscover this module, so tasks remain registered
import sys
import os

# Add parent directory to path to import tasks.py
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Note: For now, this __init__.py exists to prepare for future modularization
# Tasks are still defined in ../tasks.py
# This allows gradual migration without breaking existing imports

#!/bin/bash

# SerOps Backend Entrypoint
# Runs Django migrations, then starts Gunicorn + Celery Worker + Celery Beat.
# Set SEROPS_DEV=1 for development mode (auto-reload, solo pool, runserver).

set -e

echo "Running migrations..."
python manage.py migrate --noinput

# ---------------------------------------------------------------------------
# Development mode (auto-reload, solo pool, Django runserver)
# ---------------------------------------------------------------------------
if [ "${SEROPS_DEV:-0}" = "1" ]; then
    echo "[DEV] Starting Celery Worker (solo pool, auto-reload)..."
    watchmedo auto-restart --directory=./ --pattern='*.py' --recursive -- \
        celery -A api worker --pool=solo --loglevel=info -E \
        -Q celery,high_priority,normal,background &
    CELERY_PID=$!

    echo "[DEV] Starting Celery Beat (auto-reload)..."
    watchmedo auto-restart --directory=./ --pattern='*.py' --recursive -- \
        celery -A api beat --loglevel=info &
    BEAT_PID=$!

    echo "[DEV] Starting Django runserver..."
    python manage.py runserver 0.0.0.0:8000 &
    DJANGO_PID=$!

    trap "kill $CELERY_PID $BEAT_PID $DJANGO_PID 2>/dev/null; exit" INT TERM
    wait -n
    exit $?
fi

# ---------------------------------------------------------------------------
# Production mode (Gunicorn + Celery prefork)
# ---------------------------------------------------------------------------
WORKERS=${GUNICORN_WORKERS:-3}
THREADS=${GUNICORN_THREADS:-2}
CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-4}

echo "Starting Celery Worker (prefork, concurrency=$CELERY_CONCURRENCY)..."
celery -A api worker \
    --loglevel=info \
    --concurrency="$CELERY_CONCURRENCY" \
    -E \
    -Q celery,high_priority,normal,background \
    --max-tasks-per-child=1000 &
CELERY_PID=$!

echo "Starting Celery Beat..."
celery -A api beat --loglevel=info &
BEAT_PID=$!

echo "Starting Gunicorn (workers=$WORKERS, threads=$THREADS)..."
gunicorn api.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "$WORKERS" \
    --threads "$THREADS" \
    --timeout 120 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile - \
    --log-level info &
GUNICORN_PID=$!

# Trap signals — graceful shutdown of all child processes
shutdown() {
    echo "Shutting down..."
    kill $CELERY_PID $BEAT_PID $GUNICORN_PID 2>/dev/null
    wait $CELERY_PID $BEAT_PID $GUNICORN_PID 2>/dev/null
    exit 0
}
trap shutdown INT TERM

# Wait for any process to exit — if one dies, stop everything
wait -n
EXIT_CODE=$?
echo "Process exited with code $EXIT_CODE — shutting down remaining services..."
shutdown

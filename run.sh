#!/bin/bash

# Exit immediately if any command fails
set -e

echo "Applying database migrations..."
python manage.py migrate

echo "Collecting static files..."
python manage.py collectstatic --noinput

# ✅ FIXED: the original had no --workers, --timeout, or --threads flags.
# That means Gunicorn ran with 1 worker and the default 30-second timeout.
# One slow DB query or AI call would block ALL requests — causing the 502s.
#
# --pool=solo: single-threaded Celery worker — saves RAM on the 512MB free tier.
# --loglevel=warning: reduces log noise so real errors are visible.
echo "Starting Celery worker..."
celery -A budget worker \
  --loglevel=warning \
  --pool=solo \
  --time-limit=90 \
  --soft-time-limit=60 &

# ✅ FIXED Gunicorn config:
# --workers 2          → 2 processes so one slow request doesn't block everything
# --threads 2          → 2 threads per worker (handles concurrent requests cheaply)
# --worker-class gthread → uses threads, much lower memory than extra processes
# --timeout 120        → gives AI calls and imports time to finish (was 30s before)
# --keep-alive 5       → keeps connections alive so Render's proxy doesn't drop them
# --log-level warning  → only log real problems, not every request
echo "Starting Gunicorn..."
exec gunicorn budget.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --threads 2 \
  --worker-class gthread \
  --timeout 120 \
  --keep-alive 5 \
  --log-level warning
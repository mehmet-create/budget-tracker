#!/bin/bash

# 1. Exit immediately if any command fails
set -e

# 2. Apply Database Migrations (CRITICAL for Supabase)
# This ensures your tables exist before the code runs.
echo "Applying database migrations..."
python manage.py migrate

# 3. Collect Static Files
# Ensures CSS/JS works on the live site.
echo "Collecting static files..."
python manage.py collectstatic --noinput

# 4. Start the Celery worker
# --pool=solo is perfect for free tier (saves RAM).
# We removed '--concurrency' because 'solo' doesn't support it.
echo "Starting Celery..."
celery -A budget worker --loglevel=info --pool=solo &

# 5. Start the Django Web Server
# We ADDED '--bind 0.0.0.0:8000' so Render can actually see the website.
echo "Starting Gunicorn..."
gunicorn budget.wsgi:application --bind 0.0.0.0:8000
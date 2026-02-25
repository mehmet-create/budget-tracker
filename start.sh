#!/bin/sh

# Start script for the Render deployment
# Configuring Celery and Gunicorn

# Start Gunicorn and Celery workers

# Set the variables
export APP_MODULE="myapp:app"  # Replace 'myapp' with your app's module name
export WORKERS=3  # Number of Gunicorn workers
export CELERY_WORKERS=2  # Number of Celery workers
export CELERY_BROKER_URL="redis://localhost:6379/0"  # Change if you're using a different broker
export CELERY_RESULT_BACKEND="redis://localhost:6379/0"  # Change based on your configuration

# Start Gunicorn
exec gunicorn ${APP_MODULE} --workers ${WORKERS} --bind 0.0.0.0:8000

# Start Celery
celery -A myapp worker --loglevel=info --concurrency=${CELERY_WORKERS}
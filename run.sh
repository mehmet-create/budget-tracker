#!/bin/bash

# 1. Exit immediately if any command fails
set -e

# 2. Start the Celery worker
# We use -A budget to link to your budget/celery.py file.
# --pool=solo is often more stable for single-container free-tier setups.
celery -A budget worker --loglevel=info --concurrency 2 --pool=solo &

# 3. Give Celery a moment to establish its connection
sleep 3

# 4. Start the Django Web Server
gunicorn budget.wsgi:application
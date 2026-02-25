#!/bin/bash

# Start the Celery worker
celery -A your_project_name worker --loglevel=info &

# Start the Gunicorn server
gunicorn your_project_name.wsgi:application --bind 0.0.0.0:8000
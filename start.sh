#!/bin/bash

# Navigate to the project directory
cd /path/to/your/project

# Start Celery with optimized configurations for Render deployment
celery -A your_project_name worker --loglevel=info &

# Start Gunicorn with 512MB memory limit
exec gunicorn --bind 0.0.0.0:8000 your_project_name.wsgi:application --workers 2 --timeout 30
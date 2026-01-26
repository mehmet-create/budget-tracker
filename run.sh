#!/bin/bash

# Start the Celery worker in the background (&)
celery -A budget worker --loglevel=info --concurrency 2 &

# Start the Django Web Server
gunicorn budget.wsgi:application
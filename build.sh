#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input --clear

# Force migrations even if Django is confused
python manage.py migrate --no-input --fake-initial

# Run the admin script
python create_admin.py
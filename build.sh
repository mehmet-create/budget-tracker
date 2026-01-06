set -o errexit

pip install -r requirements.txt

mkdir -p staticfiles
python manage.py collectstatic --no-input
python manage.py migrate --no-input

python create_admin.py
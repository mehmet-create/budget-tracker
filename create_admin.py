import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'budget.settings')

django.setup()

from django.contrib.auth.models import User

def create_superuser():
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD")
    email = os.getenv("ADMIN_EMAIL", "admin@example.com")

    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username, email, password)
        print(f"Superuser '{username}' created successfully.")
    else:
        print(f"Superuser '{username}' already exists.")

if __name__ == "__main__":
    create_superuser()
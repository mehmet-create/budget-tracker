# 💰 Budget Tracker App

A professional Django-based budget tracking application featuring custom currency support, secure environment management, and JSON-ready error handling.

## 🚀 Key Features
* **Secure Authentication:** Email verification, password change with validation
* **Transaction Management:** Add, edit, delete, bulk import (CSV/Excel)
* **Budget Goals:** Set and track monthly spending targets by category
* **Dashboard Analytics:** Visual charts and spending insights
* **Multi-Currency Support:** ₦, $, €, £
* **AI Receipt Scanning:** Extract transaction data from receipt images
* **Rate Limiting:** Protection against brute force attacks
* **Async Tasks:** Background email sending with Celery
* **Global Error Handling:** Custom 403, 404, and 500 handlers
* **Production Ready:** Security headers, HTTPS, logging

## 🛠️ Tech Stack
* **Framework:** Django 5.2
* **Database:** PostgreSQL (production), SQLite (development)
* **Caching:** Redis
* **Task Queue:** Celery
* **Email:** Gmail (dev), Resend (prod)
* **AI:** Google Gemini API
* **Deployment:** Docker, Render

## ⚙️ Local Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/budget-tracker.git
   cd budget-tracker
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Mac/Linux
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

6. **Create superuser:**
   ```bash
   python manage.py createsuperuser
   ```

7. **Start Redis (in separate terminal):**
   ```bash
   redis-server
   ```

8. **Start Celery worker (in separate terminal):**
   ```bash
   celery -A budget worker --loglevel=info
   ```

9. **Run development server:**
   ```bash
   python manage.py runserver
   ```

10. **Access the app:**
    ```
    http://127.0.0.1:8000
    ```

## 🐳 Docker Setup

```bash
docker-compose up --build
```

## 📝 Environment Variables

Create a `.env` file based on `.env.example`:

```env
# Required
SECRET_KEY=your-secret-key
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3

# Email (Gmail for development)
EMAIL_HOST_USER=your-email@gmail.com
GMAIL_APP_PASSWORD=your-app-password

# Optional
GEMINI_API_KEY=your-api-key
REDIS_URL=redis://127.0.0.1:6379/0
```

## 🚀 Production Deployment

See [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) for complete guide.

Key production settings:
- Set `DEBUG=False`
- Use PostgreSQL database
- Configure Resend for emails
- Set strong `SECRET_KEY`
- Enable HTTPS
- Configure Redis for production

## 📚 Usage

### User Registration
1. Sign up with email
2. Receive verification code
3. Verify account
4. Login

### Add Transactions
- Manual entry
- CSV/Excel bulk import
- AI receipt scanning (upload image)

### Set Budget Goals
1. Navigate to Goals
2. Set monthly targets by category
3. Track progress on dashboard

### View Analytics
- Dashboard: Overview + recent transactions
- Charts: Category breakdowns
- Transaction List: Filter and search

## 🔒 Security Features
- CSRF protection
- Rate limiting (login, registration)
- Password validation
- Email verification
- Secure session cookies (production)
- HTTPS redirect (production)
- SQL injection protection (Django ORM)
- XSS protection (template escaping)

## 🧪 Testing

```bash
python manage.py test tracker
```

## 📂 Project Structure

```
budget/
├── budget/              # Project settings
│   ├── settings.py
│   ├── urls.py
│   ├── celery.py
├── tracker/             # Main app
│   ├── models.py        # Database models
│   ├── views.py         # View logic
│   ├── forms.py         # Django forms
│   ├── services.py      # Business logic
│   ├── ai_services.py   # AI integration
│   ├── templates/       # HTML templates
│   ├── static/          # CSS, JS
├── staticfiles/         # Collected static files
├── requirements.txt     # Python dependencies
├── docker-compose.yml   # Docker configuration
└── .env.example         # Environment template
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

## 📄 License

This project is licensed under the MIT License.

## 👤 Author

**Your Name**
- GitHub: [@mehmet-create](https://github.com/mehmet-create)

## 🙏 Acknowledgments

- Django Community
- Bootstrap
- Chart.js
- Font Awesome
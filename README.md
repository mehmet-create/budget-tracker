# 💰 Budget Tracker App

A professional Django-based budget tracking and financial intelligence application with AI-powered receipt scanning and subscription auditing.

## 🚀 Key Features

**Authentication & Security**
* Email verification for registration
* Password change with validation
* Password reset via email
* Account deletion with confirmation
* Rate limiting on login/registration (10 tries/60 seconds)
* Secure session management

**Transaction Management**
* Add/edit/delete transactions manually
* Bulk import via CSV or Excel
* AI receipt scanning (extract from images)
* Transaction filtering by date range
* Category-based organization

**Budget Planning**
* Set monthly budget goals by category
* Track spending progress
* Visual category breakdown
* Multiple months/years history

**Analytics & Insights**
* Dashboard with overview and recent activity
* Line charts for spending trends
* Category pie charts
* Spend audit tool

**AI Features**
* **Receipt Scanning:** Google Gemini 2.5 Flash for receipt image analysis
* **Subscription Audit:** Groq Llama 3.3 to identify recurring charges and duplicates
* Streaming text analysis for detailed spending insights

**Multi-Currency Support**
* ₦ Nigerian Naira, $ USD, € EUR, £ GBP
* Per-user currency settings

**Production Ready**
* CSRF protection with trusted origins
* HSTS headers for HTTPS enforcement
* XSS protection and clickjacking prevention
* SQL injection protection (Django ORM)
* Custom error handlers (403, 404, 500)
* Comprehensive logging

## 🛠️ Tech Stack
* **Framework:** Django 5.2
* **Database:** PostgreSQL (production), SQLite (development)
* **Static Files:** WhiteNoise
* **Email:** Gmail SMTP (dev), Resend API (prod)
* **AI/ML:** Google Gemini API, Groq API
* **Frontend:** Bootstrap, Chart.js, jQuery
* **Deployment:** Render (recommended)

## ⚙️ Local Setup

1. **Clone repository:**
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

4. **Configure environment variables:**
   Create `.env` file in the `budget/` directory:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. **Run database migrations:**
   ```bash
   python manage.py migrate
   ```

6. **Create superuser (optional, for admin access):**
   ```bash
   python manage.py createsuperuser
   ```

7. **Start development server:**
   ```bash
   python manage.py runserver
   ```

8. **Access the application:**
   ```
   http://127.0.0.1:8000
   ```

## 🐳 Docker Setup

```bash
docker-compose up --build
```

The app will be available at `http://localhost:8000`

## 📝 Environment Variables

Create a `.env` file in `budget/` directory:

```env
# Django Settings (Required)
SECRET_KEY=your-long-random-secret-key
DEBUG=True                          # Set to False in production
RENDER_EXTERNAL_HOSTNAME=           # Your Render domain (if deploying)

# Database
DATABASE_URL=sqlite:///db.sqlite3   # SQLite for dev, PostgreSQL for prod
# Example PostgreSQL: postgres://user:password@localhost:5432/budget_db

# Email (Gmail - Development)
EMAIL_HOST_USER=your-email@gmail.com
GMAIL_APP_PASSWORD=your-16char-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com

# Email (Resend - Production alternative)
RESEND_API_KEY=re_xxxxx

# AI Services
GEMINI_API_KEY=AIzaSy...             # Google Gemini (receipt scanning)
GROQ_API_KEY=gsk_...                 # Groq (subscription audit)
```

**Getting API Keys:**
- **Gmail App Password:** [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- **Gemini API:** [aistudio.google.com](https://aistudio.google.com)
- **Groq API:** [console.groq.com](https://console.groq.com) (free tier: 14,400 requests/day)

## 🚀 Production Deployment

See [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) for complete guide.

**Before deploying, ensure:**
- ✅ `DEBUG=False` in production `.env`
- ✅ Use PostgreSQL database (not SQLite)
- ✅ Set strong, random `SECRET_KEY`
- ✅ Update `ALLOWED_HOSTS` with your domain
- ✅ Configure Resend API for transactional emails
- ✅ HTTPS/SSL certificates configured
- ✅ All API keys rotated and secured
- ✅ Database backups enabled

**Recommended deployment:** Render with PostgreSQL addon

## 📚 Usage Guide

### User Registration & Authentication
1. Click **Register** on login page
2. Enter email, username, name, password
3. Receive verification code via email
4. Enter verification code on confirmation page
5. Login with credentials
6. Access dashboard

### Manage Transactions
- **Add Single:** Dashboard → "Add Transaction" 
- **Bulk Import:** Transactions → "Import CSV/Excel"
  - Supported columns: `date`, `description`, `amount`, `category`, `type`
- **AI Receipt Scanning:** Click camera icon → upload receipt photo
  - Extracts: date, amount, merchant, category
- **Edit/Delete:** Click transaction row for options

### Set Budget Goals
1. Navigate to **Goals** section
2. Click **Set Budget** 
3. Select category and enter monthly limit
4. Save - progress displays on dashboard as percentage

### View Analytics
- **Dashboard:** Current month overview + recent transactions
- **Charts:** Visual breakdown by category (pie chart) + trends (line chart)
- **Audit Tool:** Identify recurring subscriptions
  - Analyzes your transactions for duplicate charges
  - Flags potential savings opportunities

### Profile Settings
- Change currency (₦/$/€/£)
- Update email address (requires verification)
- Change password
- Delete account (permanent)

## 🔒 Security Features

**Attack Prevention**
- Rate limiting (10 attempts per 60 seconds on login/registration)
- CSRF token validation on all state-changing operations
- SQL injection protection via Django ORM parameterization
- Template auto-escaping prevents XSS attacks

**Data Protection (Production)**
- HTTPS/SSL enforcement with redirect
- Secure session cookies (httponly, secure flags)
- HSTS header with 1-year preload
- Content Security Policy headers
- Clickjacking protection (X-Frame-Options: DENY)

**Authentication Security**
- Password validation (minimum requirements)
- Email verification for registration
- Secure password reset with token expiration
- Session timeout protection

**API Security**
- API key validation on external service calls
- Error messages don't expose sensitive details
- Comprehensive error logging

## 🧪 Testing

```bash
# Run all tests
python manage.py test tracker

# Run specific test module
python manage.py test tracker.tests.TestTransactionModel

# With verbose output
python manage.py test tracker -v 2
```

## 📂 Project Structure

```
budget/
├── budget/                  # Django project settings
│   ├── settings.py         # Configuration (security, databases, apps)
│   ├── urls.py             # URL routing
│   ├── wsgi.py             # WSGI app for deployment
│   └── asgi.py             # ASGI app for async support
│
├── tracker/                 # Main application
│   ├── models.py           # Database models (User, Transaction, BudgetGoal)
│   ├── views.py            # View logic - all endpoints (~1500 lines)
│   ├── forms.py            # Django forms (validation)
│   ├── services.py         # Business logic
│   ├── ai_services.py      # AI integrations (Gemini, Groq)
│   ├── urls.py             # App-level routing
│   ├── ratelimit.py        # Rate limiting middleware
│   ├── schemas.py          # Data validation DTOs
│   ├── decorators.py       # Custom decorators
│   ├── context_processors.py # Template context helpers
│   ├── exceptions.py       # Custom exceptions
│   ├── signals.py          # Django signals
│   ├── tests.py            # Unit tests
│   ├── utils.py            # Utility functions (email sending)
│   ├── migrations/         # Database migrations
│   ├── templates/tracker/  # HTML templates
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── transactions.html
│   │   ├── goals.html
│   │   ├── charts.html
│   │   ├── audit.html
│   │   └── auth/
│   ├── static/tracker/     # CSS, JavaScript files
│   └── prompts/            # AI prompt templates
│
├── staticfiles/            # Collected static files (production)
├── templates/              # Project-wide templates
├── manage.py               # Django CLI
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (gitignored)
├── .env.example            # Environment template
├── .gitignore              # Git ignore rules
├── docker-compose.yml      # Docker configuration
├── Dockerfile              # Container image
├── build.sh                # Build script
├── run.sh                  # Run script
├── create_admin.py         # Admin creation helper
├── README.md               # This file
├── DEPLOYMENT_CHECKLIST.md # Deployment guide
└── STATUS_REPORT.md        # Project status
```

**Key Files:**
- `views.py` - Core application logic (1500+ lines)
- `models.py` - Database schema (User, Transaction, BudgetGoal, BudgetLock)
- `ai_services.py` - Gemini & Groq API integrations
- `settings.py` - Django configuration with security hardening

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/AmazingFeature`
3. Make your changes
4. Commit: `git commit -m 'Add AmazingFeature'`
5. Push: `git push origin feature/AmazingFeature`
6. Open a Pull Request

**Before submitting:**
- Run tests: `python manage.py test tracker`
- Check code style: `flake8 tracker`
- Verify no hardcoded secrets

## 📄 License

This project is licensed under the MIT License - see LICENSE file for details.

## 👤 Author

**Israel Omotayo**
- GitHub: [@mehmet-create](https://github.com/mehmet-create)
- Email: omotayoisrael24@gmail.com

## 🙏 Acknowledgments

- **Django Community** - Web framework
- **Google Gemini API** - Receipt scanning
- **Groq API** - Subscription analysis
- **Bootstrap** - UI framework
- **Chart.js** - Data visualization
- **Font Awesome** - Icons
- **PostgreSQL** - Database
- **Render** - Deployment platform

## 📞 Support & Feedback

Found a bug? Have a feature request? Please open an issue on GitHub.

## 🗺️ Roadmap

- [ ] Mobile app (React Native)
- [ ] Recurring transaction templates
- [ ] Budget notifications
- [ ] Export to PDF/email reports
- [ ] Dark mode
- [ ] Investment tracking
- [ ] Tax report generation
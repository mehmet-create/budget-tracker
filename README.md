# 💰 Budget Tracker App

A professional Django-based budget tracking application featuring custom currency support, secure environment management, and JSON-ready error handling.

## 🚀 Key Features
* **Secure Authentication:** Custom password change logic with JSON responses.
* **Global Error Handling:** Custom 403, 404, and 500 handlers that return JSON for API-style requests.
* **Environment Safety:** Sensitive credentials (DB, Secret Key) managed via `.env`.
* **Production Ready:** Logging configured for `DEBUG=False` environments.
* **Currency Customization:** Built-in support for multiple symbols (₦, $, €, £).

## 🛠️ Tech Stack
* **Framework:** Django
* **Database:** MySQL
* **Security:** Python-Dotenv, CSRF Protection

## ⚙️ Local Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/yourusername/your-repo-name.git](https://github.com/yourusername/your-repo-name.git)
   cd your-repo-name
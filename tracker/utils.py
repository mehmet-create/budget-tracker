import threading
import resend
from django.conf import settings

def send_async_email(to_email, subject, html_content):
    def start_sending():
        try:
            resend.Emails.send({
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            })
        except Exception as e:
            print(f"Background Email Error: {e}")

    threading.Thread(target=start_sending).start()
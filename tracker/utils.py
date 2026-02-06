import threading
import resend
from django.conf import settings

def is_json_request(request):
    """
    Returns True ONLY if the client specifically asks for JSON 
    (like Postman or an API call). 
    Returns False for standard web browsers.
    """
    accept_header = request.META.get('HTTP_ACCEPT', '')
    content_type_header = request.META.get('CONTENT_TYPE', '')

    if 'application/json' in accept_header:
        return True
    
    if 'application/json' in content_type_header:
        return True

    return False

def send_async_email(to_email, subject, html_content):
    def start_sending():
        try:
            resend.api_key = settings.RESEND_API_KEY
            resend.Emails.send({
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            })
        except Exception as e:
            print(f"Background Email Error: {e}")

    threading.Thread(target=start_sending).start()
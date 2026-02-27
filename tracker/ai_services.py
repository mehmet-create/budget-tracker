import json
import re
import logging
from django.conf import settings
from PIL import Image
from google import genai
from google.genai.types import HttpOptions

logger = logging.getLogger(__name__)

client = genai.Client(
    api_key=settings.GEMINI_API_KEY,
    http_options=HttpOptions(api_version="v1")
)


# ── Receipt Scanning ──────────────────────────────────────────────────────────

def scan_receipt(image_file):
    try:
        image_file.seek(0)
        img = Image.open(image_file)

        prompt = """
        Extract the transaction details from this receipt image.
        Return ONLY a valid JSON object with no markdown formatting.

        Required Keys:
        - "amount": The total (number only, no currency symbols).
        - "date": Date in YYYY-MM-DD format (use today's date if not visible).
        - "description": The merchant or vendor name.
        - "category": One of [food, transport, bills, housing, entertainment, shopping, health, education, other].
        """

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[prompt, img]
        )

        text = response.text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            data['type'] = 'Expense'
            return data

        logger.warning("Receipt scan: no JSON found in response")
        return None

    except Exception as e:
        logger.error("Receipt scan error: %s", e)
        return None


# ── Subscription / Spend Audit (returns structured JSON) ─────────────────────

def audit_subscriptions(transaction_text: str, start_date: str = None, end_date: str = None):
    """
    Analyse raw transaction text for a given period.
    Returns a dict with 'subscriptions' list and 'summary' string.
    """
    period_note = ""
    if start_date and end_date:
        period_note = f"The transactions are from {start_date} to {end_date}.\n"
    elif start_date:
        period_note = f"The transactions start from {start_date}.\n"

    prompt = f"""
You are a personal finance assistant helping a Nigerian user analyse their bank transactions.
{period_note}
Analyse the following transactions and identify:
1. Recurring subscriptions (Netflix, DSTV, Spotify, GOtv, Showmax, betting apps, etc.)
2. Potential duplicate payments (same service charged more than once in the period)
3. Any unusual or unexpected charges worth flagging

Transactions:
{transaction_text}

Return a valid JSON object exactly like this structure:
{{
  "subscriptions": [
    {{
      "name": "Service name",
      "cost": 4500,
      "frequency": "Monthly",
      "status": "Active",
      "advice": "One specific saving tip"
    }}
  ],
  "total_subscription_spend": 12000,
  "summary": "One paragraph summary of what you found and how much they can save."
}}

Rules:
- "status" must be one of: "Active", "Potential Duplicate", "Review"
- "cost" must be a plain number (no currency symbols)
- If no subscriptions found, return an empty subscriptions list with a helpful summary
- Return ONLY the JSON object, no markdown fences or extra text
"""

    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=[prompt]
        )

        text = response.text.replace('```json', '').replace('```', '').strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))

        logger.warning("Audit: no JSON found in response")
        return None

    except Exception as e:
        logger.error("Audit error: %s", e)
        return None


# ── Streaming Audit — yields plain text chunks ────────────────────────────────

def audit_subscriptions_stream(transaction_text: str, start_date: str = None, end_date: str = None):
    """
    Generator that streams a friendly plain-text analysis from Gemini.
    Used by the /tools/audit/stream/ SSE endpoint in views.py.

    Usage in views.py:
        def audit_stream(request):
            from django.http import StreamingHttpResponse
            text = request.POST.get('transactions', '')
            start = request.POST.get('start_date', '')
            end = request.POST.get('end_date', '')

            def stream():
                for chunk in audit_subscriptions_stream(text, start, end):
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                yield "data: {\"done\": true}\n\n"

            return StreamingHttpResponse(stream(), content_type='text/event-stream')
    """
    period_note = ""
    if start_date and end_date:
        period_note = f"These transactions cover the period {start_date} to {end_date}.\n"

    prompt = f"""
You are a friendly Nigerian personal finance assistant.
{period_note}
Read these bank transactions and give a clear, conversational analysis covering:
- What recurring subscriptions do you see? List each with amount.
- Are there any duplicate payments to flag?
- Total monthly subscription spend estimate.
- The single biggest saving opportunity.
- Any unusual or large charges worth questioning.

Write in plain paragraphs — NOT JSON, NOT bullet points.
Be specific with amounts and merchant names. Keep it to 4-5 short paragraphs.

Transactions:
{transaction_text}
"""

    try:
        for chunk in client.models.generate_content_stream(
            model='gemini-2.0-flash',
            contents=[prompt]
        ):
            if chunk.text:
                yield chunk.text
    except Exception as e:
        logger.error("Streaming audit error: %s", e)
        yield f"\n[Analysis error: {e}]"
import json
import re
import logging
import urllib.request
from django.conf import settings
from PIL import Image
from google import genai
from google.genai.types import HttpOptions

logger = logging.getLogger(__name__)

# ── Gemini client — receipt scanning only (needs vision) ─────────────────────
gemini_client = genai.Client(
    api_key=settings.GEMINI_API_KEY,
    http_options=HttpOptions(api_version="v1beta")
)


def _groq_chat(prompt: str, max_tokens: int = 2048) -> str:
    """
    Call Groq's REST API using only Python stdlib — no extra packages.
    Model: llama-3.3-70b-versatile — free, 14,400 requests/day.
    Get your key at: https://console.groq.com
    """
    api_key = getattr(settings, 'GROQ_API_KEY', None)
    if not api_key:
        raise ValueError("GROQ_API_KEY is missing — add it to your .env file. Get a free key at console.groq.com")
    if not str(api_key).startswith('gsk_'):
        raise ValueError(f"GROQ_API_KEY looks invalid (got: {str(api_key)[:8]}...). It should start with 'gsk_'")

    payload = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error(f"Groq API Error {e.code}: {body}")
        if e.code == 403:
            raise RuntimeError(
                f"Groq API access forbidden (403). This may mean:\n"
                f"1. Your API key is invalid or expired - get a new one at console.groq.com\n"
                f"2. Cloudflare is blocking your region/IP\n"
                f"3. Your account may be suspended\n"
                f"Error details: {body[:200]}"
            )
        raise RuntimeError(f"Groq API {e.code}: {body[:300]}")


# ── Receipt Scanning — Gemini 2.5 Flash (vision required) ────────────────────

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

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
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


# ── Spend Audit — Groq Llama (14,400 req/day free, no quota issues) ──────────

def audit_subscriptions(transaction_text: str, start_date: str = None, end_date: str = None):
    period_note = ""
    if start_date and end_date:
        period_note = f"The transactions are from {start_date} to {end_date}.\n"
    elif start_date:
        period_note = f"The transactions start from {start_date}.\n"

    prompt = f"""You are a personal finance assistant helping a Nigerian user analyse their bank transactions.
{period_note}
Analyse the following transactions and identify:
1. Recurring subscriptions (Netflix, DSTV, Spotify, GOtv, Showmax, betting apps, etc.)
2. Potential duplicate payments (same service charged more than once)
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
  "summary": "One paragraph summary of findings."
}}

Rules:
- "status" must be one of: "Active", "Potential Duplicate", "Review"
- "cost" must be a plain number (no currency symbols)
- If no subscriptions found, return empty list with a helpful summary
- Return ONLY the JSON, no markdown fences"""

    try:
        text = _groq_chat(prompt)
        text = text.replace('```json', '').replace('```', '').strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        logger.warning("Audit: no JSON in Groq response")
        return None
    except Exception as e:
        logger.error("Audit error: %s", e)
        return None


def audit_subscriptions_stream(transaction_text: str, start_date: str = None, end_date: str = None):
    """Yields plain-text analysis. Uses Groq — no Gemini quota needed."""
    period_note = ""
    if start_date and end_date:
        period_note = f"These transactions cover {start_date} to {end_date}.\n"

    prompt = f"""You are a friendly Nigerian personal finance assistant.
{period_note}
Read these transactions and give a clear conversational analysis:
- Recurring subscriptions (list each with amount)
- Any duplicate payments
- Total monthly subscription spend estimate
- Biggest saving opportunity
- Any unusual charges

Write in plain paragraphs, NOT JSON, NOT bullet points. 4-5 short paragraphs.

Transactions:
{transaction_text}"""

    try:
        text = _groq_chat(prompt, max_tokens=1024)
        yield text
    except Exception as e:
        logger.error("Streaming audit error: %s", e)
        yield f"\n[Analysis error: {e}]"
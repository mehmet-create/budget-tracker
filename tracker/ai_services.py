import json
import re
from django.conf import settings
from PIL import Image
from google import genai
from google.genai.types import HttpOptions

# 1. Initialize Client on v1 (Stable)
client = genai.Client(
    api_key=settings.GEMINI_API_KEY,
    http_options=HttpOptions(api_version="v1")
)

def scan_receipt(image_file):
    try:
        image_file.seek(0)
        img = Image.open(image_file)

        # 2. Strong Prompt (Replaces the complex config)
        prompt = """
        Extract the transaction details from this receipt image.
        Return ONLY a valid JSON object with no markdown formatting.
        
        Required Keys:
        - "amount": The total (number only).
        - "date": Date in YYYY-MM-DD format (use today's date if not visible).
        - "description": The Merchant Name.
        - "category": One of [food, rent, bills, entertainment, shopping, transport, other].
        """

        # 3. Use Gemini 2.5 Flash (The Working Model)
        # We removed the 'config' parameter to avoid the 400 Error
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=[prompt, img]
        )
        
        # 4. robust cleaning logic
        # Finds the JSON structure inside the text even if the AI adds extra words
        text = response.text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            clean_text = match.group(0)
            data = json.loads(clean_text)
            data['type'] = 'expense'
            return data
        else:
            print("No JSON found in response")
            return None

    except Exception as e:
        print(f"Gemini AI Error: {e}")
        return None
    
def audit_subscriptions(transaction_text):
    try:
        prompt = f"""
        Analyze this raw transaction text and identify recurring subscriptions:
        {transaction_text}

        Return a valid JSON object with a list of subscriptions. 
        For each, include:
        - "name": Service name (e.g. Netflix)
        - "cost": Amount
        - "status": "Active" or "Potential Duplicate"
        - "advice": One sentence on how to save (e.g. "Switch to annual plan").
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=[prompt]
        )
        
        # Clean and parse (just like we did for receipts)
        text = response.text.replace('```json', '').replace('```', '').strip()
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return None

    except Exception as e:
        print(f"Audit Error: {e}")
        return None    
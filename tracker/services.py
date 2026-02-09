import random
from datetime import timedelta
import datetime as dt
from django.utils import timezone
from django.contrib.auth import get_user_model, authenticate
from django.db import transaction
from .models import UserProfile, Transaction
from .schemas import *
from django.utils.crypto import get_random_string
from django.contrib.auth.hashers import make_password, check_password
from .models import BudgetGoal
from .schemas import SetGoalDTO, TransactionDTO
from django.shortcuts import get_object_or_404
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from django.conf import settings
from google import genai
from google.genai import types
import csv
import json
import io
import re
User = get_user_model()

class ServiceError(Exception):
    pass

class PermissionError(ServiceError):
    pass

def register_user(dto):
    with transaction.atomic():
        existing_user = User.objects.filter(email=dto.email).first()

        if existing_user:
            if existing_user.is_active:
                raise ServiceError("Email already registered.")
            
            profile, _ = UserProfile.objects.get_or_create(user=existing_user)
            
            if profile.code_generated_at and timezone.now() < (profile.code_generated_at + timedelta(seconds=60)):
                raise ServiceError("Please wait a minute before requesting a new code.")
            
            if User.objects.filter(username=dto.username).exclude(id=existing_user.id).exists():
                raise ServiceError("Username taken.")

            # Hostile Takeover (Overwrite data)
            existing_user.username = dto.username
            existing_user.set_password(dto.password)
            existing_user.first_name = dto.first_name
            existing_user.last_name = dto.last_name
            existing_user.save()
            
            raw_code = get_random_string(6, allowed_chars='0123456789')
            profile.email_verification_code = make_password(raw_code)
            profile.code_generated_at = timezone.now()
            profile.save()
            
            return existing_user, profile.email_verification_code

        if User.objects.filter(username=dto.username).exists():
            raise ServiceError("Username taken.")

        user = User.objects.create_user(
            username=dto.username,
            email=dto.email,
            password=dto.password,
            first_name=dto.first_name, 
            last_name=dto.last_name
        )
        user.is_active = False
        user.save()

        profile, created = UserProfile.objects.get_or_create(user=user)
        
        raw_code = get_random_string(6, allowed_chars='0123456789')
        profile.email_verification_code = make_password(raw_code)
        profile.code_generated_at = timezone.now()
        profile.save()
        
        return user, raw_code

def login_service(request, data: LoginDTO):
    user = authenticate(request, username=data.username, password=data.password)
    if user:
        return user, "success"

    try:
        potential_user = User.objects.get(username=data.username)
        is_valid = potential_user.check_password(data.password)
        
        if is_valid and not potential_user.is_active:
            return potential_user, "unverified"
    except User.DoesNotExist:
        pass
        
    return None, "invalid"

def verify_code(data: VerifyCodeDTO, acting_user_id: int = None):
    if acting_user_id and acting_user_id != data.user_id:
        raise PermissionError("Security Alert: Authorization failed.")

    try:
        user = User.objects.get(id=data.user_id)
        profile = user.userprofile
        
        if not profile.email_verification_code:
            raise ServiceError("No verification pending.")
        if not check_password(data.code, profile.email_verification_code):
            return False, "Invalid verification code."

        user.is_active = True
        user.save()
        
        profile.email_verification_code = None
        profile.resend_count = 0
        profile.cooldown_until = None
        profile.save()
        return True, "Account verified, Please log in."
    except User.DoesNotExist:
        raise ServiceError("User not found.")

def resend_code(data: ResendCodeDTO):
    try:
        user = User.objects.get(id=data.user_id)
        profile = user.userprofile
        now = timezone.now()

        if profile.cooldown_until and now < profile.cooldown_until:
            wait = int((profile.cooldown_until - now).total_seconds())
            raise ServiceError(f"Please wait {wait} seconds.")

        profile.resend_count += 1
        next_cooldown = 1 if profile.resend_count <= 3 else 5 * (2**(profile.resend_count - 4))
        profile.cooldown_until = timezone.now() + timedelta(minutes=min(next_cooldown, 1440))
        
        raw_code = get_random_string(6, allowed_chars='0123456789')
        profile.email_verification_code = make_password(raw_code)
        profile.save()
        
        return True, raw_code, user.email
    except User.DoesNotExist:
        raise ServiceError("User not found.")

def request_email_change(dto: EmailChangeRequestDTO):
    if User.objects.filter(email=dto.new_email).exists():
        raise ValueError("This email address is already in use.")

    profile = UserProfile.objects.get(user_id=dto.user_id)
    
    if profile.last_email_change:
        now = timezone.now()
        time_since_last_change = now - profile.last_email_change
        
        if time_since_last_change < timedelta(hours=24):
            wait_time = timedelta(hours=24) - time_since_last_change
            hours, remainder = divmod(int(wait_time.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            
            raise ValueError(f"You can only change your email once every 24 hours. Please wait {hours}h {minutes}m.")

    profile.pending_email = dto.new_email
    
    profile.resend_count = 1
    profile.cooldown_until = timezone.now() + timedelta(minutes=1) 
    
    raw_code = get_random_string(6, allowed_chars='0123456789')
    profile.email_verification_code = make_password(raw_code)
    
    profile.save()
    return raw_code

def verify_email_change(data: VerifyEmailChangeDTO):
    try:
        user = User.objects.get(id=data.user_id)
        profile = user.userprofile
    except User.DoesNotExist:
        return False, "User not found."
    if not profile.pending_email or not profile.email_verification_code:
         return False, "No active email change request found."
    if not check_password(data.code, profile.email_verification_code):
        return False, "Invalid verification code."

    user.email = profile.pending_email
    user.save()
    
    profile.last_email_change = timezone.now()
    profile.email_verification_code = None
    profile.pending_email = None
    profile.resend_count = 0
    profile.cooldown_until = None
    profile.save()
    return True, "Email updated successfully."

def change_password(user, data: PasswordChangeDTO):
    user = User.objects.get(id=data.user_id)
    
    if not user.check_password(data.old_password):
        return False, "Old password is incorrect."

    # 2. Logic Checks
    if data.new_password == data.old_password:
        return False, "New password cannot be the same as the old one."

    # 3. Save
    user.set_password(data.new_password)
    user.save()
    
    return True, "Password changed successfully."

def delete_account(data: DeleteAccountDTO):
    user = User.objects.get(id=data.user_id)
    is_correct = user.check_password(data.password)
    if not is_correct:
        raise ServiceError("Incorrect password.")
    
    user.delete()
    return True, "Account deleted."

def create_transaction(dto: TransactionDTO):
    """Creates a new transaction from DTO"""
    return Transaction.objects.create(
        user_id=dto.user_id,
        amount=dto.amount,
        type=dto.transaction_type,
        category=dto.category,
        date=dto.date,
        description=dto.description
    )

def update_transaction(transaction_id: int, dto: TransactionDTO):
    """Updates an existing transaction"""
    # We filter by user_id inside the query to ensure ownership
    txn = get_object_or_404(Transaction, id=transaction_id, user_id=dto.user_id)
    
    txn.amount = dto.amount
    txn.type = dto.transaction_type
    txn.category = dto.category
    txn.date = dto.date
    txn.description = dto.description
    txn.save()
    return txn

def delete_transaction(transaction_id: int, user_id: int):
    """Deletes a transaction safely"""
    txn = get_object_or_404(Transaction, id=transaction_id, user_id=user_id)
    txn.delete()
    return True

# --- HELPER: Modern AI Categorization Engine ---
def get_categories_from_ai(descriptions):
    """
    Sends a batch of descriptions to Gemini using the modern SDK.
    Returns a dictionary: {'Uber': 'Transport', 'Spar': 'Food'}
    """
    if not hasattr(settings, 'GEMINI_API_KEY') or not settings.GEMINI_API_KEY:
        print("AI SKIPPED: No API Key found.")
        return {}

    unique_descs = list(set(descriptions))
    if not unique_descs: return {}

    # 1. Initialize Modern Client
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
    except Exception as e:
        print(f"AI Client Init Failed: {e}")
        return {}

    # 2. The Prompt
    prompt = f"""
    You are a Nigerian financial assistant. Map these transaction descriptions to ONE category: 
    [Food, Transport, Bills, Housing, Entertainment, Shopping, Salary, Income, Other].

    Rules:
    1. "Airtime", "Data", "MTN", "Airtel", "9mobile", "Glo" -> Bills.
    2. "Uber", "Bolt", "Indriver", "Fuel", "Petrol", "Oil" -> Transport.
    3. "Water", "Coke", "Drinks", "Spar", "Shoprite", "Market", "Kitchen", "Food" -> Food.
    4. "Bet", "Sporty", "1xbet", "Football", "Wallet" -> Entertainment.
    5. "Transfer" -> Other (unless context is clear).
    
    Input List:
    {json.dumps(unique_descs)}

    Return ONLY a JSON Object mapping "Description" : "Category".
    """

    try:
        # 3. Call Gemini with Native JSON Mode
        response = client.models.generate_content(
            model='gemini-2.0-flash', # Using a faster, modern model
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json' # 👈 This guarantees valid JSON
            )
        )
        
        # 4. Parse (No need to strip markdown anymore!)
        return json.loads(response.text)
        
    except Exception as e:
        print(f"AI Categorization Failed: {e}")
        return {}

# --- HELPER: Excel Date ---
def excel_date_to_datetime(serial):
    base_date = dt.datetime(1899, 12, 30)
    delta = dt.timedelta(days=serial)
    return base_date + delta

# --- MAIN SERVICE ---
def import_transactions_service(dto):
    uploaded_file = dto.file
    filename = uploaded_file.name.lower()
    raw_rows = []

    # 1. READ FILE
    if filename.endswith('.xlsx'):
        wb = load_workbook(uploaded_file, data_only=True)
        sheet = wb.active
        raw_rows = list(sheet.values)
    elif filename.endswith('.csv'):
        try:
            data_set = uploaded_file.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            data_set = uploaded_file.read().decode('latin-1')
        io_string = io.StringIO(data_set)
        reader = csv.reader(io_string)
        raw_rows = list(reader)

    # 2. FIND HEADERS
    def normalize_header(value):
        return re.sub(r'\s+', ' ', str(value).strip().lower())

    date_keywords = ['date', 'time', 'posting date', 'transaction date']
    money_keywords = ['money', 'amount', 'credit', 'debit', 'withdrawal', 'deposit', 'inflow', 'outflow', 'balance']

    header_row_index = None
    col_map = {}

    for idx, row in enumerate(raw_rows):
        if not row: continue
        row_str_list = [normalize_header(cell) for cell in row if cell is not None]
        has_date = any(any(k in s for k in date_keywords) for s in row_str_list)
        has_money = any(any(k in s for k in money_keywords) for s in row_str_list)

        if has_date and has_money:
            header_row_index = idx
            for col_idx, cell in enumerate(row):
                if cell is None: continue
                val = normalize_header(cell)
                if any(k in val for k in ['date', 'time']): col_map['date'] = col_idx
                elif any(k in val for k in ['money in', 'credit', 'deposit', 'inflow']): col_map['money_in'] = col_idx
                elif any(k in val for k in ['money out', 'debit', 'withdrawal', 'outflow']): col_map['money_out'] = col_idx
                elif any(k in val for k in ['amount', 'value']): col_map['amount'] = col_idx
                elif any(k in val for k in ['description', 'details', 'narration', 'memo', 'narrative']): col_map['desc'] = col_idx
            break

    if header_row_index is None:
        raise ValueError("Could not find valid headers (Date & Amount) in the file.")

    # 3. PREPARE AI BATCH
    rows_to_process = []
    descriptions_to_classify = []
    
    for i, row in enumerate(raw_rows[header_row_index + 1:]):
        if 'date' not in col_map: continue
        date_val = row[col_map['date']]
        if date_val is None or str(date_val).strip() == '': continue

        # Date Parsing
        date_obj = None
        if isinstance(date_val, (dt.datetime, dt.date)): date_obj = date_val
        elif isinstance(date_val, (int, float)):
            try: date_obj = excel_date_to_datetime(date_val)
            except: continue
        else:
            date_str = str(date_val).strip()
            formats = ['%d/%m/%Y %H:%M:%S', '%d/%m/%y %H:%M:%S', '%d/%m/%Y', '%Y-%m-%d']
            for fmt in formats:
                try:
                    date_obj = dt.datetime.strptime(date_str, fmt)
                    break
                except ValueError: continue
        
        if not date_obj: continue

        # Amount Logic
        money_in_idx = col_map.get('money_in')
        money_out_idx = col_map.get('money_out')
        amount_idx = col_map.get('amount')
        final_amount = 0
        transaction_type = 'Expense'

        def clean_money(val):
            if val is None: return 0
            if isinstance(val, (int, float)): return float(val)
            clean = str(val).replace('₦', '').replace(',', '').replace(' ', '').strip()
            try: return float(clean)
            except: return 0

        if money_in_idx is not None or money_out_idx is not None:
            val_in = clean_money(row[money_in_idx]) if money_in_idx is not None and len(row) > money_in_idx else 0
            val_out = clean_money(row[money_out_idx]) if money_out_idx is not None and len(row) > money_out_idx else 0
            if val_in > 0:
                final_amount = val_in
                transaction_type = 'Income'
            elif val_out > 0:
                final_amount = val_out
                transaction_type = 'Expense'
        elif amount_idx is not None and len(row) > amount_idx:
            raw_amt = clean_money(row[amount_idx])
            final_amount = abs(raw_amt)
            transaction_type = 'Expense' if raw_amt < 0 else 'Income'

        if final_amount == 0: continue

        # Description
        desc_idx = col_map.get('desc')
        description = str(row[desc_idx]).strip() if desc_idx is not None and len(row) > desc_idx else "Transaction"
        if not description or description.lower() == 'nan': description = "Imported Transaction"
        
        rows_to_process.append({
            'date': date_obj,
            'amount': final_amount,
            'desc': description,
            'type': transaction_type
        })
        descriptions_to_classify.append(description)

    # 4. CALL AI (Smart Categorization)
    print(f"Asking AI to categorize {len(set(descriptions_to_classify))} items...")
    ai_category_map = get_categories_from_ai(descriptions_to_classify)
    
    # Fallback Map (Your Safety Net)
    FALLBACK_MAP = {
        'Food': ['food', 'restaurant', 'burger', 'pizza', 'chicken', 'spar', 'shoprite', 'market', 'coke', 'water', 'kitchen'],
        'Transport': ['uber', 'bolt', 'fuel', 'petrol', 'oil', 'taxify', 'ride'],
        'Bills': ['airtime', 'data', 'mtn', 'glo', '9mobile', 'airtel', 'nepa', 'phcn', 'dstv', 'gotv'],
        'Entertainment': ['netflix', 'spotify', 'bet', 'sporty', '1xbet', 'football', 'movie'],
        'Housing': ['rent', 'carpenter', 'plumber'],
        'Shopping': ['jumia', 'konga', 'amazon', 'clothes', 'shoe']
    }

    # 5. SAVE
    success_count = 0
    for item in rows_to_process:
        desc_clean = item['desc']
        final_category = 'Other'

        # Priority 1: AI
        if desc_clean in ai_category_map:
            final_category = ai_category_map[desc_clean]
        
        # Priority 2: Fallback Keywords (If AI said "Other" or failed)
        if final_category == 'Other':
            desc_lower = desc_clean.lower()
            for cat, keys in FALLBACK_MAP.items():
                if any(k in desc_lower for k in keys):
                    final_category = cat
                    break
        
        if item['type'] == 'Income':
            final_category = 'Income'

        Transaction.objects.create(
            user_id=dto.user_id,
            date=item['date'],
            amount=item['amount'],
            description=desc_clean.title(),
            category=final_category,
            type=item['type']
        )
        success_count += 1

    return success_count

def set_budget_goal(dto: SetGoalDTO):
    obj, created = BudgetGoal.objects.update_or_create(
        user_id=dto.user_id,
        category=dto.category,
        month=dto.month,
        year=dto.year,
        defaults={'target_amount': dto.target_amount}
    )
    return obj

def update_goal(dto: UpdateGoalDTO):
    goal = get_object_or_404(BudgetGoal, pk=dto.goal_id, user_id=dto.user_id)
    goal.category = dto.category
    goal.target_amount = dto.target_amount
    goal.save()
    return goal

def import_previous_goals(dto: ImportGoalsDTO):
    with transaction.atomic():
        latest = BudgetGoal.objects.filter(user_id=dto.user_id)\
            .exclude(month=dto.target_month, year=dto.target_year)\
            .order_by('-year', '-month').first()
            
        if not latest:
            raise ServiceError("No previous goals found to import.")

        BudgetGoal.objects.filter(user_id=dto.user_id, month=dto.target_month, year=dto.target_year).delete()
        
        templates = BudgetGoal.objects.filter(user_id=dto.user_id, month=latest.month, year=latest.year)
        new_goals = [
            BudgetGoal(
                user_id=dto.user_id, 
                category=g.category, 
                target_amount=g.target_amount, 
                month=dto.target_month, 
                year=dto.target_year
            ) for g in templates
        ]
        BudgetGoal.objects.bulk_create(new_goals)
        return len(new_goals)

def update_currency(dto: UpdateCurrencyDTO):
    UserProfile.objects.update_or_create(
        user_id=dto.user_id,
        defaults={'currency_code': dto.currency_code}
    )

def resend_email_change_code(user_id: int):
    """
    Handles exponential backoff and code regeneration.
    Returns: (success: bool, result: str|tuple)
    """
    try:
        profile = UserProfile.objects.get(user_id=user_id)
    except UserProfile.DoesNotExist:
        return False, "Profile not found."

    if not profile.pending_email:
        return False, "No pending email change request found."

    if profile.cooldown_until and timezone.now() < profile.cooldown_until:
        wait_seconds = int((profile.cooldown_until - timezone.now()).total_seconds())
        minutes = wait_seconds // 60
        seconds = wait_seconds % 60
        return False, f"Please wait {minutes}m {seconds}s before resending."

    profile.resend_count += 1
    
    if profile.resend_count <= 3:
        next_cooldown_mins = 1
    else:
        next_cooldown_mins = 5 * (2 ** (profile.resend_count - 4))
    
    next_cooldown_mins = min(next_cooldown_mins, 1440)
    
    profile.cooldown_until = timezone.now() + timedelta(minutes=next_cooldown_mins)

    raw_code = get_random_string(6, allowed_chars='0123456789')
    profile.email_verification_code = make_password(raw_code)
    
    profile.save()

    return True, (raw_code, profile.pending_email)


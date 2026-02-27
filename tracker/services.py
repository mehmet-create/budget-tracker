import random
import logging
import csv
import io
import json
import re
import datetime as dt
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.hashers import make_password, check_password
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.crypto import get_random_string

from .models import UserProfile, Transaction, BudgetGoal
from .schemas import *

User = get_user_model()
logger = logging.getLogger(__name__)

# Load the categorization prompt once at startup, not on every import call
_PROMPT_PATH = Path(__file__).parent / 'prompts' / 'categorize_prompt.txt'
try:
    _PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding='utf-8')
except FileNotFoundError:
    logger.warning("categorize_prompt.txt not found at %s. AI categorization will be limited.", _PROMPT_PATH)
    _PROMPT_TEMPLATE = None


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

            if profile.code_generated_at and timezone.now() < (profile.code_generated_at + timedelta(minutes=10)):
                raise ServiceError("Please wait before requesting a new code.")

            if User.objects.filter(username=dto.username).exclude(id=existing_user.id).exists():
                raise ServiceError("Username taken.")

            existing_user.username = dto.username
            existing_user.set_password(dto.password)
            existing_user.first_name = dto.first_name
            existing_user.last_name = dto.last_name
            existing_user.save()

            raw_code = get_random_string(6, allowed_chars='0123456789')
            profile.email_verification_code = make_password(raw_code)
            profile.code_generated_at = timezone.now()
            profile.save()

            return existing_user, raw_code

        if User.objects.filter(username=dto.username, is_active=True).exists():
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

        profile, _ = UserProfile.objects.get_or_create(user=user)

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
        if potential_user.check_password(data.password) and not potential_user.is_active:
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
        return True, "Account verified. Please log in."
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
        next_cooldown = 1 if profile.resend_count <= 3 else 5 * (2 ** (profile.resend_count - 4))
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
        time_since = timezone.now() - profile.last_email_change
        if time_since < timedelta(hours=24):
            remaining = timedelta(hours=24) - time_since
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(rem, 60)
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
    if data.new_password == data.old_password:
        return False, "New password cannot be the same as the old one."

    user.set_password(data.new_password)
    user.save()
    return True, "Password changed successfully."


def delete_account(data: DeleteAccountDTO):
    user = User.objects.get(id=data.user_id)
    if not user.check_password(data.password):
        raise ServiceError("Incorrect password.")
    user.delete()
    return True, "Account deleted."


def resend_email_change_code(user_id: int):
    try:
        profile = UserProfile.objects.get(user_id=user_id)
    except UserProfile.DoesNotExist:
        return False, "Profile not found."

    if not profile.pending_email:
        return False, "No pending email change request found."

    if profile.cooldown_until and timezone.now() < profile.cooldown_until:
        wait = int((profile.cooldown_until - timezone.now()).total_seconds())
        return False, f"Please wait {wait // 60}m {wait % 60}s before resending."

    profile.resend_count += 1
    next_cooldown = 1 if profile.resend_count <= 3 else 5 * (2 ** (profile.resend_count - 4))
    profile.cooldown_until = timezone.now() + timedelta(minutes=min(next_cooldown, 1440))

    raw_code = get_random_string(6, allowed_chars='0123456789')
    profile.email_verification_code = make_password(raw_code)
    profile.save()

    return True, (raw_code, profile.pending_email)


def create_transaction(dto: TransactionDTO):
    return Transaction.objects.create(
        user_id=dto.user_id,
        amount=dto.amount,
        type=dto.transaction_type,
        category=dto.category,
        date=dto.date,
        description=dto.description
    )


def update_transaction(transaction_id: int, dto: TransactionDTO):
    txn = get_object_or_404(Transaction, id=transaction_id, user_id=dto.user_id)
    txn.amount = dto.amount
    txn.type = dto.transaction_type
    txn.category = dto.category
    txn.date = dto.date
    txn.description = dto.description
    txn.save()
    return txn


def delete_transaction(transaction_id: int, user_id: int):
    txn = get_object_or_404(Transaction, id=transaction_id, user_id=user_id)
    txn.delete()
    return True



def get_categories_from_ai(descriptions: list) -> dict:
    """
    Sends a batch of transaction descriptions to Gemini for categorization.
    The prompt is loaded from tracker/prompts/categorize_prompt.txt so the
    Nigerian context knowledge lives in a text file, not in Python code.
    """
    from google import genai
    from google.genai import types

    api_key = getattr(settings, 'GEMINI_API_KEY', None)
    if not api_key:
        logger.warning("AI categorization skipped: GEMINI_API_KEY not set.")
        return {}

    if not _PROMPT_TEMPLATE:
        logger.warning("AI categorization skipped: prompt file not found.")
        return {}

    unique = list(set(descriptions))
    if not unique:
        return {}

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        logger.error("Gemini client init failed: %s", e)
        return {}

    prompt = _PROMPT_TEMPLATE.format(descriptions=json.dumps(unique))

    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type='application/json'
            )
        )
        result = json.loads(response.text)
        valid = {'food', 'transport', 'bills', 'housing', 'entertainment',
                 'shopping', 'health', 'education', 'income', 'other'}
        return {
            k: v.lower().strip()
            for k, v in result.items()
            if isinstance(v, str) and v.lower().strip() in valid
        }
    except Exception as e:
        logger.error("AI categorization failed: %s", e)
        return {}




def import_transactions_service(dto):
    """
    Imports transactions from a CSV or XLSX bank statement.
    - Income rows → always 'income', no AI call needed.
    - All expense descriptions → one batch AI call.
    - Unrecognized → 'other'.
    - Saved with bulk_create (one DB round trip).
    """
    from openpyxl import load_workbook

    uploaded_file = dto.file
    filename = uploaded_file.name.lower()
    raw_rows = []

    # Read file
    if filename.endswith('.xlsx'):
        wb = load_workbook(uploaded_file, data_only=True)
        raw_rows = list(wb.active.values)
    elif filename.endswith('.csv'):
        try:
            data = uploaded_file.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            data = uploaded_file.read().decode('latin-1')
        raw_rows = list(csv.reader(io.StringIO(data)))

    # Detect header row
    def norm(v):
        return re.sub(r'\s+', ' ', str(v).strip().lower())

    date_kw  = {'date', 'time', 'posting date', 'transaction date', 'value date'}
    money_kw = {'money', 'amount', 'credit', 'debit', 'withdrawal',
                'deposit', 'inflow', 'outflow', 'balance', 'value'}

    header_idx = None
    col = {}

    for i, row in enumerate(raw_rows):
        if not row:
            continue
        cells = [norm(c) for c in row if c is not None]
        if (any(any(k in c for k in date_kw) for c in cells) and
                any(any(k in c for k in money_kw) for c in cells)):
            header_idx = i
            for ci, cell in enumerate(row):
                if cell is None:
                    continue
                v = norm(cell)
                if any(k in v for k in ['date', 'time']):
                    col.setdefault('date', ci)
                elif any(k in v for k in ['money in', 'credit', 'deposit', 'inflow']):
                    col['money_in'] = ci
                elif any(k in v for k in ['money out', 'debit', 'withdrawal', 'outflow']):
                    col['money_out'] = ci
                elif any(k in v for k in ['amount', 'value']):
                    col.setdefault('amount', ci)
                elif any(k in v for k in ['description', 'narration', 'details',
                                          'memo', 'narrative', 'remark']):
                    col['desc'] = ci
            break

    if header_idx is None:
        raise ValueError("Could not find valid column headers. Make sure the file has at least a Date and Amount column.")

    def clean_amount(v):
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        cleaned = re.sub(r'[₦,\s$£€NGN]', '', str(v)).strip()
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0

    def parse_date(v):
        if isinstance(v, (dt.datetime, dt.date)):
            return v
        if isinstance(v, (int, float)):
            return dt.datetime(1899, 12, 30) + dt.timedelta(days=v)
        s = str(v).strip()
        for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%y %H:%M:%S', '%d/%m/%Y',
                    '%Y-%m-%d', '%m/%d/%Y', '%d-%m-%Y', '%d-%b-%Y',
                    '%d/%b/%Y', '%Y/%m/%d'):
            try:
                return dt.datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    parsed_rows = []
    expense_descriptions = []

    for row in raw_rows[header_idx + 1:]:
        if 'date' not in col:
            continue
        raw_date = row[col['date']] if len(row) > col['date'] else None
        if raw_date is None or str(raw_date).strip() == '':
            continue

        date_obj = parse_date(raw_date)
        if not date_obj:
            continue

        mi = col.get('money_in')
        mo = col.get('money_out')
        am = col.get('amount')
        amount   = 0.0
        txn_type = 'Expense'

        if mi is not None or mo is not None:
            val_in  = clean_amount(row[mi]) if mi is not None and len(row) > mi else 0.0
            val_out = clean_amount(row[mo]) if mo is not None and len(row) > mo else 0.0
            if val_in > 0:
                amount, txn_type = val_in, 'Income'
            elif val_out > 0:
                amount, txn_type = val_out, 'Expense'
        elif am is not None and len(row) > am:
            raw = clean_amount(row[am])
            amount   = abs(raw)
            txn_type = 'Income' if raw > 0 else 'Expense'

        if amount == 0:
            continue

        di   = col.get('desc')
        desc = str(row[di]).strip() if di is not None and len(row) > di else 'Transaction'
        if not desc or desc.lower() in ('nan', 'none', ''):
            desc = 'Imported Transaction'

        parsed_rows.append({'date': date_obj, 'amount': amount, 'desc': desc, 'type': txn_type})
        if txn_type == 'Expense':
            expense_descriptions.append(desc)

    if not parsed_rows:
        raise ValueError("No valid transactions found in the file.")

    # One AI call for all expenses
    ai_map = {}
    if expense_descriptions:
        logger.info("Categorizing %d unique descriptions via AI.", len(set(expense_descriptions)))
        ai_map = get_categories_from_ai(expense_descriptions)

    valid_cats = {'food', 'transport', 'bills', 'housing', 'entertainment',
                  'shopping', 'health', 'education', 'income', 'other'}

    to_create = []
    for item in parsed_rows:
        if item['type'] == 'Income':
            category = 'income'
        else:
            category = ai_map.get(item['desc'], 'other')
            if category not in valid_cats:
                category = 'other'

        to_create.append(Transaction(
            user_id=dto.user_id,
            date=item['date'],
            amount=item['amount'],
            description=item['desc'].title(),
            category=category,
            type=item['type'],
        ))

    Transaction.objects.bulk_create(to_create, ignore_conflicts=True)
    logger.info("Imported %d transactions for user_id=%s", len(to_create), dto.user_id)
    return len(to_create)


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

        BudgetGoal.objects.filter(
            user_id=dto.user_id, month=dto.target_month, year=dto.target_year
        ).delete()

        templates = BudgetGoal.objects.filter(
            user_id=dto.user_id, month=latest.month, year=latest.year
        )
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
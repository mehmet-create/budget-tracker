import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Any
from django.utils import timezone
from django.core.files.uploadedfile import UploadedFile

@dataclass
class RegisterDTO:
    username: str
    email: str
    password: str
    first_name: str = ""
    last_name: str = ""

@dataclass
class LoginDTO:
    username: str
    password: str

@dataclass
class VerifyCodeDTO:
    user_id: int
    code: str

@dataclass
class ResendCodeDTO:
    user_id: int

@dataclass
class EmailChangeRequestDTO:
    user_id: int
    new_email: str
    current_email: str

    def __post_init__(self):
        if not self.new_email:
            raise ValueError("New email is required.")
        
        self.new_email = self.new_email.strip().lower()
        self.current_email = self.current_email.strip().lower()

        if self.new_email == self.current_email:
            raise ValueError("New email cannot be the same as your current email.")

@dataclass
class VerifyEmailChangeDTO:
    user_id: int
    code: str

@dataclass
class PasswordChangeDTO:
    user_id: int
    old_password: str
    new_password: str
    confirm_new_password: str

    def __post_init__(self):
        if not self.new_password or not self.confirm_new_password:
             raise ValueError("Both password fields are required.")

        if self.new_password != self.confirm_new_password:
            raise ValueError("New passwords do not match.")

        if len(self.new_password) < 8:
            raise ValueError("Password must be at least 8 characters long.")

@dataclass
class DeleteAccountDTO:
    user_id: int
    password: str

@dataclass
class UpdateLocationDTO:
    latitude: float
    longitude: float


@dataclass
class TransactionDTO:
    user_id: int
    amount: Decimal
    transaction_type: str
    category: str
    date: datetime.date
    description: str = ""

    VALID_CATEGORIES = {
        'income', 'food', 'transport', 'housing', 'bills',
        'entertainment', 'shopping', 'health', 'education', 'other'
    }
    VALID_TYPES = {'Income', 'Expense'}

    def __post_init__(self):
        """Validate and sanitize transaction data."""
        # Amount
        if not isinstance(self.amount, Decimal):
            try:
                self.amount = Decimal(str(self.amount))
            except Exception:
                raise ValueError("Invalid amount.")
        if self.amount <= 0:
            raise ValueError("Amount must be greater than zero.")
        if self.amount > Decimal('999999999.99'):
            raise ValueError("Amount is unrealistically large.")

        # Type
        if self.transaction_type not in self.VALID_TYPES:
            raise ValueError(f"Invalid transaction type. Must be Income or Expense.")

        # Category
        if self.category not in self.VALID_CATEGORIES:
            raise ValueError(f"Invalid category.")

        # Date
        if isinstance(self.date, str):
            for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y'):
                try:
                    self.date = datetime.datetime.strptime(self.date, fmt).date()
                    break
                except ValueError:
                    pass
        if not isinstance(self.date, datetime.date):
            raise ValueError("Invalid date format.")

        # Description — strip, cap length, no script tags
        desc = (self.description or '').strip()
        desc = desc[:255]  # enforce DB max_length
        self.description = desc  # empty string = no description, template handles display

@dataclass 
class ImportTransactionsDTO:
    user_id: int
    file: UploadedFile

    def __post_init__(self):
        if self.file.size > 2 * 1024 * 1024:
            raise ValueError("File too large. Max size is 2MB.")

        name = self.file.name.lower()
        if not name.endswith(('.csv', '.xlsx')):
            raise ValueError("Invalid format. Only CSV and Excel allowed.")

@dataclass
class SetGoalDTO:
    user_id: int
    category: str
    target_amount: Decimal
    month: Optional[int] = None
    year: Optional[int] = None

    def __post_init__(self):
        """Auto-fill defaults and validate types"""
        now = timezone.now()
        
        if not self.month:
            self.month = now.month
        if not self.year:
            self.year = now.year
            
        try:
            self.month = int(self.month)
            self.year = int(self.year)
            self.target_amount = Decimal(str(self.target_amount))
        except (ValueError, TypeError):
            raise ValueError("Invalid number format for month, year, or target.")
        if self.target_amount <= 0:
            raise ValueError("Target amount must be greater than zero.")
        if self.target_amount > Decimal('999999999.99'):
            raise ValueError("Target amount is unrealistically large.")
        if not (1 <= self.month <= 12):
            raise ValueError("Invalid month.")
        if not (2000 <= self.year <= 2100):
            raise ValueError("Invalid year.")

        if (self.year < now.year) or (self.year == now.year and self.month < now.month):
             raise ValueError(f"Cannot set goals for the past ({self.month}/{self.year})")    
        
@dataclass
class UpdateGoalDTO:
    user_id: int
    goal_id: int
    category: str
    target_amount: Decimal

@dataclass
class ImportGoalsDTO:
    user_id: int
    target_month: int
    target_year: int
    
    def __post_init__(self):
        now = timezone.now()
        if (self.target_year < now.year) or \
           (self.target_year == now.year and self.target_month < now.month):
            raise ValueError("Cannot import goals into a past month.")

@dataclass
class UpdateCurrencyDTO:
    user_id: int
    currency_code: str

    def __post_init__(self):
        valid_codes = {'NGN', 'USD', 'EUR', 'GBP'}
        if self.currency_code not in valid_codes:
            raise ValueError(f"Invalid currency code: {self.currency_code}")
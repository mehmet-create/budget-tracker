from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.password_validation import (
    MinimumLengthValidator,
    UserAttributeSimilarityValidator,
    CommonPasswordValidator,
    NumericPasswordValidator,
)
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.contrib.auth.models import User
from django.contrib.auth import get_user_model
from .models import BudgetGoal, Transaction
from django import forms

User = get_user_model()

class SignUpForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        label="Password"
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        label="Confirm Password"
    )

    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"})
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name"]

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username:
            existing_user = User.objects.filter(username__iexact=username).first()
            
            if existing_user:
                if existing_user.is_active:
                    raise forms.ValidationError("That username is already taken.")
                else:
                    existing_user.delete()
                    
        return username
    
        
    def clean_first_name(self):
        first_name = self.cleaned_data.get('first_name')
        if any(char.isdigit() for char in first_name):
            raise forms.ValidationError("Names should not contain numbers.")
        return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data.get('last_name')
        if any(char.isdigit() for char in last_name):
            raise forms.ValidationError("Names should not contain numbers.")
        return last_name
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            existing_user = User.objects.filter(email__iexact=email).first()
            
            if existing_user:
                if existing_user.is_active:
                    raise forms.ValidationError("That email address is already in use.")
                else:
                    existing_user.delete()
                    
        return email
    
    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not password:
            return password

        validators = [
            MinimumLengthValidator(min_length=8),
            UserAttributeSimilarityValidator(),
            CommonPasswordValidator(),
            NumericPasswordValidator(),
        ]

        for validator in validators:
            validator.validate(password, user=self.instance)
        
        return password
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm = cleaned_data.get("confirm_password")

        if password and confirm and password != confirm:
            self.add_error('confirm_password', "Passwords do not match.")

        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        user.email = self.cleaned_data["email"]
        user.is_active = False
        if commit:
            user.save()
        return user
    
class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['amount', 'category', 'type', 'date', 'description']
        
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control'}),
        }    
class BudgetGoalForm(forms.ModelForm):
    category = forms.ChoiceField(
        choices=[],
        label="Select Category",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    class Meta:
        model = BudgetGoal
        fields = ['category', 'target_amount']
        widgets = {
            'target_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter monthly target (e.g., 50000.00)',
                'min': '0',
                'step': '0.01'
            }),
        }
        
    def __init__(self, *args, user=None, **kwargs):
        self.user = user 
        super().__init__(*args, **kwargs)
        
        base_choices = dict(Transaction.CATEGORY_CHOICES)
        

        final_choices = []
        for key, label in base_choices.items():
            if key not in ['income', 'salary', 'deposit']: 
                final_choices.append((key, label))
        
        final_choices.sort(key=lambda x: x[1])

        self.fields['category'].choices = [('', 'Select Category...')] + final_choices

    def clean_category(self):
        category = self.cleaned_data.get('category')
        valid_keys = [c[0] for c in Transaction.CATEGORY_CHOICES]
        
        if category not in valid_keys:
            raise forms.ValidationError(f"'{category}' is not a valid category.")
            
        return category

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        
        if self.user and category:
            month = self.instance.month if self.instance.month else 0
            year = self.instance.year if self.instance.year else 0

            pass 

        return cleaned_data
class ProfileUpdateForm(forms.ModelForm):
    username = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    first_name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'})
    )
    
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email')
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in self.fields:
            self.fields[field_name].widget.attrs['class'] = 'form-control'
        self.fields['username'].label = 'Username'
        self.fields['first_name'].label = 'First Name'
        self.fields['last_name'].label = 'Last Name'

class CSVUploadForm(forms.Form):
    file = forms.FileField(
        label="Select CSV File",
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.csv'})
    )
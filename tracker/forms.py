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
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Enter password"}),
        label="Password"
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Confirm password"}),
        label="Confirm Password"
    )

    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter first Name"})
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter last Name"})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "Enter email address"})
    )
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter username"})
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username and username != self.instance.username:
            if User.objects.filter(username__iexact=username).exists():
                raise forms.ValidationError("That username is already taken.")     
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and email != self.instance.email:
            if User.objects.filter(email__iexact=email).exists():
                raise forms.ValidationError("That email address is already in use by another account.")
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
            try:
                validator.validate(password)
            except ValidationError as e:
                raise ValidationError(e.messages[0])
        
        return password

    def clean_confirm_password(self):
        password = self.cleaned_data.get("password")
        confirm = self.cleaned_data.get("confirm_password")

        if password != confirm:
            raise ValidationError("Passwords do not match.")

        return confirm
    
    def clean(self):
        cleaned_data = super().clean() 

        if 'username' in self.errors:
            username_errors = self.errors['username']
            self._errors = {} 
            self._errors['username'] = username_errors
            return cleaned_data
        
        if 'email' in self.errors:
            email_errors = self.errors['email']
            self._errors = {} 
            self._errors['email'] = email_errors

            return cleaned_data
        
        return cleaned_data
    
    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data["password"]
        user.set_password(password)
        if commit:
            user.save()
        return user
    
class BudgetGoalForm(forms.ModelForm):
    category = forms.ChoiceField(
        choices=[],
        label="Select or Define Category",
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
        
        base_choices = list(Transaction.CATEGORY_CHOICES)

        user_categories = Transaction.objects.filter(
            user=self.user,
            type='Expense'
        ).values_list('category', flat=True)

        user_categories = {c.strip().lower() for c in user_categories if c}

        merged = {value: label for value, label in base_choices}
        for c in user_categories:
            merged.setdefault(c, c.title())

        self.fields['category'].choices = [('', 'Select Category...')] + sorted(merged.items())


    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category', '').lower()
        cleaned_data['category'] = category
        
        if self.user and category:
            month = self.instance.month
            year = self.instance.year

            duplicate_check = BudgetGoal.objects.filter(
                user=self.user,
                category=category,
                month=month,
                year=year
            )

            if self.instance.pk:
                duplicate_check = duplicate_check.exclude(pk=self.instance.pk)

            if duplicate_check.exists():
                raise forms.ValidationError(
                    f"A budget goal for '{category}' already exists for {month}/{year}."
                )

        return cleaned_data
    
class ProfileUpdateForm(forms.ModelForm):
    email = forms.EmailField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'})
    )
    first_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'})
    )
    
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email')
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in self.fields:
            self.fields[field_name].widget.attrs['class'] = 'form-control'
            self.fields[field_name].label = '' 
        self.fields['username'].label = 'Username'
        self.fields['first_name'].label = 'First Name'
        self.fields['last_name'].label = 'Last Name'
        self.fields['email'].label = 'Email Address'    


class SequentialPasswordChangeForm(PasswordChangeForm):
    def clean_new_password1(self):
        password = self.data.get("new_password1")
        
        validators = [
            MinimumLengthValidator(min_length=8), 
            UserAttributeSimilarityValidator(),
            CommonPasswordValidator(),
            NumericPasswordValidator(),
        ]
        
        for validator in validators:
            try:
                validator.validate(password, user=self.user)
            except ValidationError as e:
                raise ValidationError(e.messages[0])
                
        self.cleaned_data['new_password1'] = password
        return password
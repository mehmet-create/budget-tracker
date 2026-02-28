from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm
from django.contrib.auth.password_validation import (
    MinimumLengthValidator,
    UserAttributeSimilarityValidator,
    CommonPasswordValidator,
    NumericPasswordValidator,
)
from django.contrib.auth.models import User
from django.contrib.auth import get_user_model
from .models import BudgetGoal, Transaction
from django import forms

User = get_user_model()


class SignUpForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "off"}, render_value=False),
        label="Password"
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "off"}, render_value=False),
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
            # only block if an ACTIVE user already has this username.
            # Never delete accounts here — that belongs in the service layer
            # with proper guards, not in form validation anyone can trigger.
            if User.objects.filter(username__iexact=username, is_active=True).exists():
                raise forms.ValidationError("That username is already taken.")
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
            # only block if an ACTIVE user already has this email.
            # Never delete accounts here — see clean_username note above.
            if User.objects.filter(email__iexact=email, is_active=True).exists():
                raise forms.ValidationError("That email address is already registered.")
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
        final_choices = [
            (key, label)
            for key, label in base_choices.items()
            if key not in ['income', 'salary', 'deposit']
        ]
        final_choices.sort(key=lambda x: x[1])
        self.fields['category'].choices = [('', 'Select Category...')] + final_choices

    def clean_category(self):
        category = self.cleaned_data.get('category')
        valid_keys = [c[0] for c in Transaction.CATEGORY_CHOICES]
        if category not in valid_keys:
            raise forms.ValidationError(f"'{category}' is not a valid category.")
        return category

    def clean(self):
        return super().clean()


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


class CustomPasswordResetForm(PasswordResetForm):
    """
    Custom password reset form using send_async_email (Resend HTTP API)
    instead of Django's SMTP backend for better reliability on Render.
    """
    def save(self, domain_override=None, subject_template_name='tracker/password_reset_subject.txt',
             email_template_name='tracker/password_reset_email.html', use_https=False, token_generator=None,
             from_email=None, request=None, html_email_template_name=None, extra_email_context=None, **kwargs):
        """
        Send password reset email via Resend HTTP API instead of SMTP.
        """
        from django.contrib.auth.tokens import default_token_generator
        from django.contrib.sites.shortcuts import get_current_site
        from django.template.loader import render_to_string
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from .utils import send_async_email
        import logging
        
        logger = logging.getLogger(__name__)
        
        if not domain_override:
            current_site = get_current_site(request)
            site_name = current_site.name
            domain = current_site.domain
        else:
            site_name = domain_override
            domain = domain_override
        
        token_generator = token_generator or default_token_generator
        
        for user in self.get_users(self.cleaned_data['email']):
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = token_generator.make_token(user)
            
            # Build contexts
            context = {
                'email': user.email,
                'domain': domain,
                'site_name': site_name,
                'uid': uid,
                'user': user,
                'token': token,
                'protocol': 'https' if use_https else 'http',
            }
            if extra_email_context:
                context.update(extra_email_context)
            
            # Render email subject and html
            subject = render_to_string(subject_template_name, context).strip()
            html_content = render_to_string(email_template_name, context)
            
            # Send via Resend HTTP API
            logger.info(f"Sending password reset email to {user.email} via Resend HTTP API")
            success = send_async_email(user.email, subject, html_content)
            
            if success:
                logger.info(f"Password reset email sent successfully to {user.email}")
            else:
                logger.error(f"Failed to send password reset email to {user.email}")


class CSVUploadForm(forms.Form):
    file = forms.FileField(
        label="Select CSV or Excel File",
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv'
        })
    )
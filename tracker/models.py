from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
# Create your models here.
class Transaction(models.Model):
    TYPE_CHOICES = [
        ('Income', 'Income'),
        ('Expense', 'Expense'),
    ]
    CATEGORY_CHOICES = [
        ('income', 'Income'),    
        ('food', 'Food & Dining'), 
        ('transport', 'Transport'), 
        ('housing', 'Housing'),  
        ('bills', 'Bills & Utilities'),
        ('entertainment', 'Entertainment'),
        ('shopping', 'Shopping'), 
        ('health', 'Health & Wellness'), 
        ('education', 'Education'), 
        ('other', 'Other')
]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    date = models.DateField(default=timezone.now, null=False, blank=False)
    description = models.CharField(max_length=255, blank=True, null=True)
    def save(self, *args, **kwargs):
        if not self.description:
            self.description = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.type} - {self.category} ({self.description or 'No Description'})"
User = get_user_model()

class BudgetGoal(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.CharField(
        max_length=60,
        choices=Transaction.CATEGORY_CHOICES
    )
    target_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    month = models.IntegerField() 
    year = models.IntegerField()
    
    created_at = models.DateField(default=timezone.now)

    class Meta:
        unique_together = ('user', 'category', 'month', 'year')

    def __str__(self):
        return f"{self.user.username}'s goal for {self.category} ({self.month}/{self.year})"

CURRENCY_CHOICES = [(code, code) for code, symbol in getattr(settings, 'AVAILABLE_CURRENCIES', {}).items()]

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='userprofile')
    currency_code = models.CharField(max_length=3, default='NGN', verbose_name='Preferred Currency')

    email_verification_code = models.CharField(max_length=128, null=True, blank=True)
    pending_email = models.EmailField(null=True, blank=True)
    resend_count = models.IntegerField(default=0)
    cooldown_until = models.DateTimeField(null=True, blank=True)
    code_generated_at = models.DateTimeField(null=True, blank=True)
    last_email_change = models.DateTimeField(null=True, blank=True)
    resend_count = models.IntegerField(default=0)
    cooldown_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

class BudgetLock(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    month = models.IntegerField()
    year = models.IntegerField()

    class Meta:
        unique_together = ('user', 'month', 'year')    

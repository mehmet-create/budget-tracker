from django.contrib import admin
from .models import Transaction, BudgetGoal, UserProfile
# Register your models here.
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'title', 
        'amount', 
        'type', 
        'category', 
        'date', 
    )

    list_filter = ('type', 'category', 'user')
    search_fields = ('title', 'user__username')
admin.site.register(Transaction, TransactionAdmin)

class BudgetGoalAdmin(admin.ModelAdmin):
    list_display = (
        'user', 
        'category', 
        'target_amount', 
        'created_at' 
    )
    list_filter = ('created_at', 'user', 'category', 'target_amount', 'month', 'year',)
    readonly_fields = ('month', 'year')
    search_fields = ('user__username', 'category')
admin.site.register(BudgetGoal, BudgetGoalAdmin)

class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'currency_code')
    search_fields = ('user__username',)
admin.site.register(UserProfile, UserProfileAdmin)
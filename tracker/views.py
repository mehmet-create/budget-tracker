# New optimized charts view implementation

from django.db.models import Sum, Count
from django.shortcuts import render
from .models import Transaction


def charts_view(request):
    # Optimized aggregate queries for charts
    income_data = Transaction.objects.filter(transaction_type='income').aggregate(total_income=Sum('amount'), count=Count('id'))
    expense_data = Transaction.objects.filter(transaction_type='expense').aggregate(total_expense=Sum('amount'), count=Count('id'))

    context = {
        'total_income': income_data['total_income'],
        'total_income_count': income_data['count'],
        'total_expense': expense_data['total_expense'],
        'total_expense_count': expense_data['count'],
    }
    return render(request, 'tracker/charts.html', context)
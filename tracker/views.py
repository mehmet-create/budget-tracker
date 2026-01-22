from django.shortcuts import render, redirect, get_object_or_404
from .models import Transaction, BudgetGoal, UserProfile, BudgetLock
from .forms import SignUpForm, BudgetGoalForm, ProfileUpdateForm
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib import messages
from collections import defaultdict
from django.utils import timezone
from decimal import Decimal
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy, reverse
from .forms import SequentialPasswordChangeForm, BudgetGoalForm, ProfileUpdateForm, SignUpForm
from datetime import datetime
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf import settings    
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django_ratelimit.decorators import ratelimit
from django.http import JsonResponse
import logging
from datetime import timedelta
import random
from django_ratelimit.core import get_usage
from django.contrib.auth.models import User
from django.db import transaction
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
import resend
from django.conf import settings
from datetime import timedelta
from .utils import send_async_email

# Create your views here.
@login_required(login_url='login')
def dashboard(request):
    current_month = timezone.now().month
    current_year = timezone.now().year
    user = request.user
    
    goals = BudgetGoal.objects.filter(
        user=user, 
        month=current_month, 
        year=current_year
    )
    
    expense_qs = Transaction.objects.filter(
        user=user,
        type='Expense',
        date__month=current_month,
        date__year=current_year
    ).values('category').annotate(total=Sum('amount'))

    expense_map = {i['category']: i['total'] for i in expense_qs}

    goal_progress = []

    for goal in goals:
        spent = expense_map.get(goal.category, Decimal('0.00'))

        target = float(goal.target_amount)
        spent_amt = float(spent)

        percent = (spent_amt / target) * 100 if target > 0 else 0

        goal_progress.append({
            'pk': goal.pk,
            'category': goal.category.title(),
            'target': target,
            'spent': spent,
            'percent': round(percent, 1),
            'status': 'exceeded' if percent > 100 else (
                'warning' if percent >= 80 else 'ok'
            )
        })

    all_transactions = Transaction.objects.filter(user=user)

    totals = all_transactions.aggregate(
            income=Sum('amount', filter=Q(type__iexact='Income')),
            expense=Sum('amount', filter=Q(type__iexact='Expense'))
        )

    total_income = totals['income'] or Decimal('0.0')
    total_expense = totals['expense'] or Decimal('0.0')
    balance = total_income - total_expense

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'status': 'success',
            'data': {
                'current_month': current_month,
                'current_year': current_year,
                'total_income': float(total_income),
                'total_expense': float(total_expense),
                'balance': float(balance),
                'goal_progress': goal_progress,
                'transactions': list(all_transactions.values('id', 'amount', 'type', 'category', 'date'))
            }
        }, status=200)
    context = {
        'current_month': current_month,
        'current_year': current_year,
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": balance,
        'goal_progress': goal_progress,
        "transactions": all_transactions,
    }
    return render(request, "tracker/dashboard.html", context)

MASTER_TRANSACTION_CATEGORIES = [choice[0] for choice in Transaction._meta.get_field('category').choices]

@login_required(login_url='login')
def profile_settings(request):
    user = request.user
    profile = user.userprofile

    if request.method == 'POST':
        if 'request_email_change' in request.POST:
            usage = get_usage(request, group='email_change', key='ip', rate='5/h', increment=True)
            if usage and usage['should_limit']:
                messages.error(request, "You've requested too many email codes. Please try again in an hour.")
                return redirect('profile')
            new_email = request.POST.get('email')
            if User.objects.filter(email=new_email).exclude(id=user.id).exists():
                messages.error(request, "This email is already in use.")
                return redirect('profile')
            
            if profile.last_email_change and timezone.now() < profile.last_email_change + timedelta(days=2):
                messages.error(request, "You can only change your email once every 48 hours.")
                return redirect('profile')

            code = str(random.randint(100000, 999999))
            profile.email_verification_code = code
            profile.pending_email = new_email
            profile.code_generated_at = timezone.now()
            profile.save()

            html_content = f"<strong>Your activation code is: {code}</strong>"
            send_async_email(new_email, "Your Verification Code", html_content)
            
            return redirect('verify_email_change')

        else:
            form = ProfileUpdateForm(request.POST, instance=user)
            if form.is_valid():
                form.save()
                if request.headers.get('Accept') == 'application/json':
                    return JsonResponse({'status': 'success', 'message': 'Profile updated.'})
                messages.success(request, 'Profile updated successfully.')
                return redirect('profile')
            else:
                messages.error(request, 'Please correct the errors below.')
    
    else:
        form = ProfileUpdateForm(instance=user)
        
    context = {'form': form}
    return render(request, 'tracker/profile_settings.html', context)

@login_required(login_url='login')
def verify_email_change(request):
    profile = request.user.userprofile
    
    if request.method == 'POST':
        user_code = request.POST.get('code')
        
        if not profile.email_verification_code or not profile.code_generated_at:
            messages.error(request, "No active verification request found.")
            return redirect('profile')

        expiry_time = profile.code_generated_at + timedelta(minutes=15)
        if timezone.now() > expiry_time:
            profile.email_verification_code = None
            profile.pending_email = None
            profile.save()
            messages.error(request, "Your verification code has expired. Please request a new one.")
            return redirect('profile')

        if user_code == profile.email_verification_code:
            user = request.user
            if User.objects.filter(email=profile.pending_email).exclude(id=user.id).exists():
                messages.error(request, "This email is now taken. Please choose another.")
                return redirect('profile')

            user.email = profile.pending_email
            user.save()
            
            profile.last_email_change = timezone.now()
            profile.email_verification_code = None
            profile.pending_email = None
            profile.code_generated_at = None
            profile.save()
            
            messages.success(request, "Email updated successfully!")
            return redirect('profile')
        else:
            messages.error(request, "Invalid code. Please try again.")
            
    return render(request, 'tracker/verify_email_change.html')

@login_required
def resend_verification_code(request):
    profile = request.user.userprofile
    
    if not profile.pending_email or not profile.email_verification_code:
        messages.error(request, "No pending email change found.")
        return redirect('profile')

    usage = get_usage(request, group='email_resend', key='ip', rate='3/h', increment=True)
    if usage and usage['should_limit']:
        messages.error(request, "Too many resend attempts. Please wait.")
        return redirect('verify_email_change')

    html_content = f"""
        <p>You requested to change your email address.</p>
        <p>Your verification code is: <strong>{profile.email_verification_code}</strong></p>
    """
    send_async_email(profile.pending_email, "Verify Your New Email", html_content)
    messages.success(request, f"Code resent to {profile.pending_email}")
    
    return redirect('verify_email_change')
class CustomPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    login_url = 'login'
    form_class = SequentialPasswordChangeForm
    template_name = "tracker/password_change_form.html"
    success_url = reverse_lazy("password_change_done")

    def form_valid(self, form):
        user = form.save()
        update_session_auth_hash(self.request, user)
        
        if self.request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'status': 'success', 
                'message': 'Password changed successfully!'
            }, status=200)
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'status': 'error', 
                'errors': form.errors.get_json_data() 
            }, status=400)
        return super().form_invalid(form)
    
@login_required(login_url='login')    
def password_change_done_custom(request):
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'status': 'success', 'message': 'Password changed successfully.'})
    return render(request, 'tracker/password_change_done.html')    

@login_required(login_url='login')
def transaction_list(request):
    user = request.user
    transaction_categories = Transaction.objects.filter(user=user).values_list('category', flat=True)
    goal_categories = BudgetGoal.objects.filter(user=user).values_list('category', flat=True)
    all_categories = set(list(transaction_categories) + list(goal_categories))
    all_categories.add("General") 


    all_transactions = Transaction.objects.filter(user=user).order_by('-date', '-id')

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            
            if end_date:
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()

                all_transactions = all_transactions.filter(date__range=[start_date_obj, end_date_obj])
            else:
                all_transactions = all_transactions.filter(date=start_date_obj)

        except ValueError:
            messages.warning(request, "Invalid date format provided for filtering.")

    query = request.GET.get('q')
    
    if query:
        all_transactions = all_transactions.filter(
            Q(description__icontains=query) |
            Q(category__icontains=query) 
        )        

    page_number = request.GET.get('page')
    paginator = Paginator(all_transactions, 20)    

    try:
        transactions_page = paginator.page(page_number)
    except PageNotAnInteger:
        transactions_page = paginator.page(1)
    except EmptyPage:
        transactions_page = paginator.page(paginator.num_pages)

    total_income = all_transactions.filter(type='Income').aggregate(Sum('amount'))['amount__sum'] or 0
    total_expense = all_transactions.filter(type='Expense').aggregate(Sum('amount'))['amount__sum'] or 0   
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'status': 'success',
            'data': {
                'transactions': list(transactions_page.object_list.values(
                    'id', 'amount', 'type', 'category', 'description', 'date'
                )),
                'categories': list(MASTER_TRANSACTION_CATEGORIES),
                'current_sort': request.GET.get('sort', '-date'),
                'current_query': request.GET.get('q'),
                'current_start_date': request.GET.get('start_date'),
                'current_end_date': request.GET.get('end_date'),
                'total_income_period': float(total_income),
                'total_expense_period': float(total_expense),
                'total_balance_period': float(total_income - total_expense),
                'pagination': {
                    'has_next': transactions_page.has_next(),
                    'has_previous': transactions_page.has_previous(),
                    'current_page': transactions_page.number,
                    'total_pages': paginator.num_pages,
                }
            }
        }, status=200)
    context = {
            'transactions': transactions_page,
            'categories': MASTER_TRANSACTION_CATEGORIES,
            'current_sort': request.GET.get('sort', '-date'),
            'current_query': request.GET.get('q'),
            'current_start_date': request.GET.get('start_date'),
            'current_end_date': request.GET.get('end_date'),
            'total_income_period': total_income,
            'total_expense_period': total_expense,
            'total_balance_period': total_income - total_expense
        }
    return render(request, 'tracker/transaction_list.html', context)

AVAILABLE_CURRENCIES = settings.AVAILABLE_CURRENCIES

@login_required(login_url='login')
def change_currency(request):
    if request.method == 'POST' and request.user.is_authenticated:
        currency_code = request.POST.get('currency_code')
        currency_symbol = settings.AVAILABLE_CURRENCIES.get(currency_code)

        if currency_symbol:
            request.session['currency_symbol'] = currency_symbol

            try:
                profile = request.user.userprofile 
                profile.currency_code = currency_code
                profile.save()
            except UserProfile.DoesNotExist:
                 UserProfile.objects.create(user=request.user, currency_code=currency_code)

            messages.success(request, f"Currency changed to {currency_code} ({currency_symbol})")
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'status': 'success',
                'message': f'Currency changed to {currency_code} ({currency_symbol})',
                'currency_code': currency_code,
                'currency_symbol': currency_symbol
            }, status=200)
        
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required(login_url='login')
def add_transaction(request):
    user = request.user
    if request.method == 'POST':
        try:
            amount_str = request.POST.get('amount')
            transaction_type = request.POST.get('type')
            category_name = request.POST.get('category')
            description = request.POST.get('description')
            date = request.POST.get('date')
            
            if not all([amount_str, transaction_type, category_name, date]):
                if request.headers.get('Accept') == 'application/json':
                    return JsonResponse({'status': 'error', 'message': 'Missing required fields'}, status=400)
                messages.error(request, "Please fill out all required fields.")
                return redirect('add_transaction') 

            amount = Decimal(amount_str)

            Transaction.objects.create(
                user=user,
                type=transaction_type,
                amount=amount,
                category=category_name,
                description=description,
                date=date
            )
            
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    'status': 'success',
                    'message': 'Transaction added successfully!',
                    'data': {
                        'id': user.id,
                        'amount': float(amount),
                        'type': transaction_type,
                        'category': category_name,
                        'description': description,
                        'date': str(date)
                    }
                }, status=201)
            
            messages.success(request, "Transaction added successfully!")
            return redirect('transactions')
            
        except (TypeError, ValueError, Exception) as e:
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, f"Failed to add transaction. Check amount format or date: {e}")
            return redirect('add_transaction') 
        
    categories = Transaction.CATEGORY_CHOICES
    context = {
        'categories': categories,
    }
    return render(request, 'tracker/add_transaction.html', context)

@login_required(login_url='login')
def charts(request):
    transactions = Transaction.objects.filter(user=request.user)

    total_income = 0.0
    total_expense = 0.0
    category_totals = defaultdict(float)

    for t in transactions:
        try:
            amount = float(t.amount)
            if t.type == "Income":
                total_income += amount
            elif t.type == "Expense":
                total_expense += amount
                category_totals[t.category] += amount
        except (ValueError, TypeError):
            continue

    balance = total_income - total_expense
    
    if balance >= 0:
        balance_status = 'positive'
        balance_color = '#4CAF50'
    else:
        balance_status = 'negative'
        balance_color = '#F44336'
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'status': 'success',
            'data': {
                'total_income': total_income,
                'total_expense': total_expense,
                'balance': balance,
                'balance_status': balance_status,
                'balance_color': balance_color,
                'category_labels': list(category_totals.keys()),
                'category_values': list(category_totals.values()),
            }
        }, status=200)
    context = {
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": balance,
        "balance_status": balance_status,
        "balance_color": balance_color,
        "category_labels": list(category_totals.keys()),
        "category_values": list(category_totals.values()),
    }

    return render(request, "tracker/charts.html", context)

@login_required(login_url='login')
def edit_transaction(request, pk):
    transaction = get_object_or_404(Transaction, pk=pk, user=request.user)

    if request.method == "POST":
        try:
            transaction.amount = Decimal(request.POST.get("amount", 0))
            transaction.type = request.POST.get("type")
            transaction.category = request.POST.get("category")
            transaction.date = request.POST.get("date")
            transaction.description = request.POST.get("description")
            transaction.save()
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    'status': 'success',
                    'message': 'Transaction updated successfully!',
                    'data': {
                        'id': transaction.id,
                        'amount': float(transaction.amount),
                        'type': transaction.type,
                        'category': transaction.category,
                        'description': transaction.description,
                        'date': str(transaction.date)
                    }
                }, status=200)
            messages.success(request, 'Transaction updated successfully.')
            return redirect("transactions")
        except Exception as e:
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, f"Failed to update transaction. Error: {e}")
            print(f"Failed to update transaction: {e}")


    return render(request, "tracker/editTransaction.html", {"transaction": transaction})

@login_required(login_url='login')
def delete_transaction(request, pk):
    transaction = Transaction.objects.filter(pk=pk, user=request.user).first()

    if not transaction:
        if request.headers.get('Accept') == 'application/json' or request.method == "DELETE":
            return JsonResponse({
                'status': 'error',
                'message': f'Transaction with ID {pk} not found.'
            }, status=404)
        return render(request, '404.html', status=404)

    if request.method in ["DELETE", "POST"]:
        transaction.delete()
        
        if request.headers.get('Accept') == 'application/json' or request.method == "DELETE":
            return JsonResponse({
                'status': 'success',
                'message': 'Transaction deleted successfully.',
                'id': pk
            }, status=200)

        messages.success(request, 'Transaction deleted successfully.')
        return redirect('transactions') 
    return render(request, 'tracker/delete_confirm.html', {'transaction': transaction})

@login_required(login_url='login')
def goals_list(request, year=None, month=None):
    user = request.user
    now = timezone.now()
    categories = Transaction.CATEGORY_CHOICES
    view_month = month or request.GET.get('month') or now.month
    view_year = year or request.GET.get('year') or now.year

    view_year = int(view_year)
    view_month = int(view_month)
    is_history = (view_year < now.year) or (view_year == now.year and view_month < now.month)

    current_goals = BudgetGoal.objects.filter(
    user=user,
    year=view_year,
    month=view_month
    ).order_by('category')

    has_history_to_copy = BudgetGoal.objects.filter(user=user).exclude(
        month=view_month, year=view_year
    ).exists()

    can_import = not is_history and not current_goals.exists()

    expense_totals = (
        Transaction.objects
        .filter(
            user=user,
            type='Expense',
            date__year=view_year,
            date__month=view_month
        )
        .values('category')
        .annotate(total=Sum('amount'))
    )

    expense_map = {
        item['category']: item['total']
        for item in expense_totals
    }

    for goal in current_goals:
        spent = expense_map.get(goal.category, Decimal('0.00'))

        goal.actual_spent = spent
        goal.remaining = goal.target_amount - spent

        if goal.target_amount > 0:
            goal.progress_percent = min(
                (float(spent) / float(goal.target_amount)) * 100,
                100
            )
        else:
            goal.progress_percent = 0



    all_months = [
    (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
    (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
    (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
]
    year_choices = [now.year, now.year - 1, now.year - 2]

    if view_year == now.year:
        months_choices = [m for m in all_months if m[0] <= now.month]
    else:
        months_choices = all_months
    valid_month_nums = [m[0] for m in months_choices]
    if view_month not in valid_month_nums:
        view_month = now.month
    if request.headers.get('Accept') == 'application/json':
        goals_data = [{
            'id': goal.id,
            'category': goal.category,
            'target_amount': float(goal.target_amount),
            'actual_spent': float(goal.actual_spent),
            'remaining': float(goal.remaining),
            'progress_percent': round(goal.progress_percent, 2),
            'is_over_budget': goal.remaining < 0,
            'date_period': f"{goal.year}-{goal.month:02d}",
        } for goal in current_goals]
            
        return JsonResponse({
            'status': 'success',
            'view_period': {'month': view_month, 'year': view_year},
            'data': {'goals': goals_data}
        }, status=200)
    context = {
        'goals': current_goals,
        'categories': categories,
        'view_month': view_month,
        'view_year': view_year,
        'months_choices': months_choices,
        'year_choices': year_choices,
        'is_history': is_history,
        'can_import': can_import,
    }
    return render(request, 'tracker/goals_list.html', context)

@login_required(login_url='login')
def clear_monthly_goals(request, year, month):
    now = timezone.now()
    if year < now.year or (year == now.year and month < now.month):
        return JsonResponse({'status': 'error', 'message': 'Cannot clear goals from previous months.'}, status=403)
    
    deleted_count, _ = BudgetGoal.objects.filter(
        user=request.user, 
        year=year, 
        month=month
    ).delete()
    
    BudgetLock.objects.get_or_create(user=request.user, year=year, month=month)

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'status': 'success',
            'message': f'Cleared {deleted_count} goals for {month}/{year}. Auto-fill disabled for this month.',
            'deleted_count': deleted_count
        })

    messages.warning(request, f"Cleared {deleted_count} goals. Auto-fill disabled for this month.")
    return redirect(reverse('goals_list') + f"?year={year}&month={month}")

@login_required(login_url='login')
def import_previous_goals(request):
    user = request.user
    view_month = int(request.GET.get('month', timezone.now().month))
    view_year = int(request.GET.get('year', timezone.now().year))

    latest_record = BudgetGoal.objects.filter(user=user).exclude(
        month=view_month, year=view_year
    ).order_by('-year', '-month').first()

    if latest_record:
        template_goals = BudgetGoal.objects.filter(
            user=user, month=latest_record.month, year=latest_record.year
        )
        BudgetGoal.objects.filter(user=user, month=view_month, year=view_year).delete()
        new_goals = [
            BudgetGoal(
                user=user, 
                category=g.category, 
                target_amount=g.target_amount,
                month=view_month, 
                year=view_year
            ) for g in template_goals
        ]
        BudgetGoal.objects.bulk_create(new_goals)

        if 'BudgetLock' in globals() or 'BudgetLock' in locals():
             BudgetLock.objects.filter(user=user, month=view_month, year=view_year).delete()

        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'status': 'success',
                'message': 'Goals imported successfully!',
                'imported_goals': [{
                    'category': g.category,
                    'target_amount': float(g.target_amount)
                } for g in new_goals]
            }, status=201)
        messages.success(request, "Goals imported successfully!")

    else:
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'status': 'info',
                'message': 'No previous goals found to import.'
            }, status=200)
        messages.warning(request, "No previous goals found to import.")

    return redirect(reverse('goals_list') + f"?year={view_year}&month={view_month}")

@login_required(login_url='login')
def set_goals(request):
    user = request.user
    categories = Transaction.CATEGORY_CHOICES
    if request.method == 'POST':
        category = None
        try:
            category = request.POST.get('category')
            target = Decimal(request.POST.get('target_amount'))
            
            if not category or not target:
                raise ValueError("Category and Target Amount are required.")
            
            BudgetGoal.objects.update_or_create(
                user=user,
                category=category,
                month=timezone.now().month,
                year=timezone.now().year,
                defaults={'target_amount': target}
            )

            BudgetLock.objects.filter(user=user, month=timezone.now().month, year=timezone.now().year).delete()
            category_label = dict(categories).get(category, category)
            
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    'status': 'success',
                    'message': f'Goal set for {category_label}',
                    'data': {'category': category_label, 'target': float(target)}
                }, status=201)

            messages.success(request, f'Goal set for {category_label}.')
            return redirect('goals_list')
        
        except Exception as e:
            if category:
                error_msg = f"Error setting goal for {category}: {e}"
            messages.error(request, error_msg)
            return redirect('goals_list')

    context = {
        'categories': categories,
    }
    return render(request, 'tracker/goals_list.html', context)   

@login_required(login_url='login')
def edit_goal(request, pk):
    categories = Transaction.CATEGORY_CHOICES
    goal = BudgetGoal.objects.filter(pk=pk, user=request.user).first()
    now = timezone.now()
    if goal.year < now.year or (goal.year == now.year and goal.month < now.month):
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'status': 'error', 'message': 'Past goals cannot be edited.'}, status=403)
        messages.error(request, "You cannot edit goals from previous months.")
        return redirect('goals_list')
    if not goal:
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'status': 'error',
                'message': f'Budget Goal with ID {pk} not found.'
            }, status=404)
        return render(request, '404.html', status=404)
    user = request.user

    if request.method == 'POST':
        form = BudgetGoalForm(request.POST, instance=goal, user=user)

        if form.is_valid():
            form.save()
            
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    'status': 'success',
                    'message': f"Budget goal for '{goal.category}' updated successfully.",
                    'data': {
                        'id': goal.pk,
                        'category': goal.category,
                        'target_amount': str(goal.target_amount)
                    }
                }, status=200)

            messages.success(request, f"Budget goal updated successfully.")
            return redirect(reverse('goals_list') + f"?year={goal.year}&month={goal.month}")

        else:
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    'status': 'error',
                    'errors': form.errors.get_json_data()
                }, status=400)
            
            messages.error(request, "The was an error saving your goal.")
            
    else:
        form = BudgetGoalForm(instance=goal, user=user)
   
    context = {
        'form': form,
        'goal': goal,
        'categories': categories,
    }
    return render(request, 'tracker/edit_goal.html', context)

@login_required(login_url='login')
def delete_goal(request, pk):
    goal = BudgetGoal.objects.filter(pk=pk, user=request.user).first()
    if request.method in ["POST", "DELETE"]:
        if not goal:
            return JsonResponse({'status': 'error', 'message': 'Goal not found', 'id': pk}, status=404)

        category_name = goal.category
        goal.delete()

        if request.headers.get('Accept') == 'application/json' or request.method == "DELETE":
            return JsonResponse({'status': 'success', 'message': 'Deleted successfully', 'id': pk}, status=200)

        messages.success(request, f"Budget goal for '{category_name}' deleted.")
        return redirect('dashboard')

    if not goal:
        return render(request, '404.html', status=404)
    return render(request, 'tracker/delete_goal.html', {'goal': goal})

logger = logging.getLogger(__name__)

@ratelimit(key='ip', rate='10/m', block=False)
@ratelimit(key='post:username', rate='5/m', block=False)
def login_view(request):
    if request.session.get('unverified_user_id'):
        messages.info(request, "Please verify your email before logging in.")
        return redirect('verify_registration')
    if getattr(request, 'limited', False):
        messages.error(request, "Too many attempts. Please try again in 1 minute.")
        return render(request, 'tracker/login.html')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                temp_user = User.objects.get(username=username)
                if temp_user.check_password(password) and not temp_user.is_active:
                    messages.warning(request, "Account not verified. Check your email.")
                    request.session['unverified_user_id'] = temp_user.id
                    return redirect('verify_registration')
            except User.DoesNotExist:
                pass
            messages.error(request, "Invalid username or password.")
    return render(request, 'tracker/login.html')      

@ratelimit(key='ip', rate='5/m', block=False)
@ratelimit(key='post:email', rate='3/m', block=False)
def register_view(request):
    if getattr(request, 'limited', False):
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'status': 'error', 'message': 'Too many attempts.'}, status=429)
        messages.error(request, "Too many registration attempts. Please wait.")
        return redirect('register')
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
                    
                    profile, created = UserProfile.objects.get_or_create(user=user)                    
                    
                    code = str(random.randint(100000, 999999))
                    profile.email_verification_code = code
                    profile.save()
                    html_content = f"<strong>Your activation code is: {code}</strong>"
                    send_async_email(user.email, "Your Verification Code", html_content)
                    messages.success(request, f"A new code has been sent to {user.email}")
                    request.session['unverified_user_id'] = user.id
                    if request.headers.get('Accept') == 'application/json':
                        return JsonResponse({
                            'status': 'success',
                            'message': 'Verification code sent to email.',
                            'next_step': 'verify_registration',
                            'data': {
                                'user_id': user.id,
                                'username': user.username,
                                'email': user.email
                            }
                        }, status=201)
                    return redirect('verify_registration')

            except Exception as e:
                if request.headers.get('Accept') == 'application/json':
                    return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
                print(f"DEBUG: {e}")
                messages.error(request, "An error occurred during registration. Please try again.")
                return redirect('register')
                
        else:
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({
                    'status': 'error',
                    'message': 'Validation failed.',
                    'errors': form.errors.get_json_data()
                }, status=400)
    else:        
        form = SignUpForm()
        
    return render(request, 'tracker/register.html', {'form': form})

@csrf_protect
def verify_registration(request):
    user_id = request.session.get('unverified_user_id')
    if not user_id:
        return redirect('register')

    try:
        user = User.objects.get(id=user_id)
        profile = user.userprofile
    except User.DoesNotExist:
        return redirect('register')

    remaining_seconds = 0
    if profile.cooldown_until and profile.cooldown_until > timezone.now():
        delta = profile.cooldown_until - timezone.now()
        remaining_seconds = int(delta.total_seconds())

    if request.method == 'POST':
        user_code = request.POST.get('code')

        if user_code and user_code == profile.email_verification_code:
            user.is_active = True
            user.save()
            
            profile.email_verification_code = None
            profile.resend_count = 0
            profile.cooldown_until = None
            profile.save()
            
            messages.success(request, "Account verified! You can now log in.")
            if 'unverified_user_id' in request.session:
                del request.session['unverified_user_id']
            return redirect('login')
        else:
            messages.error(request, "Invalid verification code.")

    return render(request, 'tracker/verify_registration.html', {
        'email': user.email,
        'remaining_seconds': remaining_seconds
    })

@csrf_protect
@require_POST
def resend_code(request):
    user_id = request.session.get('unverified_user_id')
    
    if not user_id:
        messages.error(request, "Your session expired. Please register again.")
        return redirect('register')

    try:
        user = User.objects.get(id=user_id)
        profile, created = UserProfile.objects.get_or_create(user=user)
        now = timezone.now()
        if profile.cooldown_until and now < profile.cooldown_until:
            wait_seconds = int((profile.cooldown_until - now).total_seconds())
            minutes = wait_seconds // 60
            seconds = wait_seconds % 60
            messages.error(request, f"Please wait {minutes}m {seconds}s before requesting a new code.")
            return redirect('verify_registration')
    
        profile.resend_count += 1
        if profile.resend_count <= 3:
            next_cooldown_mins = 1 
        else:
            next_cooldown_mins = 5 * (2 ** (profile.resend_count - 4))
            next_cooldown_mins = min(next_cooldown_mins, 1440)
        profile.cooldown_until = now + timedelta(minutes=next_cooldown_mins)

        new_code = str(random.randint(100000, 999999))
        profile.email_verification_code = new_code
        profile.save()

        html_content = f"<strong>Your activation code is: {new_code}</strong>"
        send_async_email(user.email, "Your Verification Code", html_content)
        messages.success(request, f"A new code has been sent to {user.email}")
        
    except User.DoesNotExist:
        messages.error(request, "User not found.")
        return redirect('register')
    except Exception as e:
        messages.error(request, "Failed to send email. Please try again later.")
        print(f"SMTP Error: {e}")
    return redirect('verify_registration')

def cancel_registration(request):
    user_id = request.session.get('unverified_user_id')
    if user_id:
        User.objects.filter(id=user_id, is_active=False).delete()
        del request.session['unverified_user_id']
        messages.warning(request, "Registration cancelled.")
    return redirect('register')

def cleanup_unverified_users():
    threshold = timezone.now() - timedelta(hours=24)
    User.objects.filter(is_active=False, date_joined__lt=threshold).delete()

def logout_view(request):
    
    if request.session.get('unverified_user_id'):
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'status': 'redirect',
                'url': '/cancel-registration/'
            }, status=200)
        
        return redirect('cancel_registration')

    logout(request)

    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({
            'status': 'success',
            'message': 'You have been logged out.'
        }, status=200)

    messages.info(request, 'You have been logged out.')
    return redirect('login')

def custom_403_handler(request, exception=None):
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'status': 'error', 'message': 'Forbidden (403)'}, status=403)
    return render(request, 'errors/403.html', status=403)

def custom_404_handler(request, exception):
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'status': 'error', 'message': 'Not Found (404)'}, status=404)
    return render(request, 'errors/404.html', status=404)

def custom_500_handler(request):
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'status': 'error', 'message': 'Internal Server Error (500)'}, status=500)
    return render(request, 'errors/500.html', status=500)

def csrf_failure_json(request, reason=""):
    return JsonResponse({'status': 'error', 'message': f'CSRF Failure: {reason}'}, status=403)
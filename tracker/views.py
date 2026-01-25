import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from decimal import Decimal

# Django Imports
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import alogin, logout, update_session_auth_hash, get_user_model
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf import settings
from asgiref.sync import sync_to_async

# Local Imports
from .models import Transaction, BudgetGoal, UserProfile, BudgetLock
from .forms import SignUpForm, BudgetGoalForm, ProfileUpdateForm
from . import services, schemas
from .tasks import send_email_task
from .ratelimit import check_ratelimit, RateLimitError

logger = logging.getLogger(__name__)
User = get_user_model()

# ==========================================
#  HELPERS
# ==========================================
def get_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    return x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')

def is_json_request(request):
    return request.headers.get('Accept') == 'application/json'

# ==========================================
#  SECTION 1: ASYNC AUTHENTICATION
#  (Fixed: Uses await request.auser() for safe DB access)
# ==========================================

async def login_view(request):
    try:
        await check_ratelimit(f"login_ip_{get_ip(request)}", limit=10, period=60)
    except RateLimitError as e:
        if is_json_request(request): return JsonResponse({'error': str(e)}, status=429)
        messages.error(request, str(e))
        return await sync_to_async(render)(request, 'tracker/login.html')

    if request.method == 'POST':
        dto = schemas.LoginDTO(
            username=request.POST.get('username'),
            password=request.POST.get('password')
        )
        user, status = await services.login_service(request, dto)

        if is_json_request(request):
            if status == "success":
                await alogin(request, user)
                return JsonResponse({'status': 'success', 'user': user.username})
            return JsonResponse({'status': 'error', 'code': status}, status=401)

        if status == "success":
            await alogin(request, user)
            return redirect('dashboard')
        elif status == "unverified":
            messages.warning(request, "Account not verified.")
            await sync_to_async(request.session.__setitem__)('unverified_user_id', user.id)
            return redirect('verify_registration')
        else:
            messages.error(request, "Invalid credentials.")

    return await sync_to_async(render)(request, 'tracker/login.html')

async def register_view(request):
    try:
        await check_ratelimit(f"reg_ip_{get_ip(request)}", limit=50, period=3600)
    except RateLimitError as e:
        if is_json_request(request): return JsonResponse({'error': str(e)}, status=429)
        messages.error(request, str(e))
        return redirect('login')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        is_valid = await sync_to_async(form.is_valid)()

        if is_valid:
            try:
                # Use 'password' matching your forms.py
                dto = schemas.RegisterDTO(
                    username=form.cleaned_data['username'],
                    email=form.cleaned_data['email'],
                    password=form.cleaned_data['password'] 
                )
                user, code = await services.register_user(dto)
                
                send_email_task.delay(user.email, "Verification Code", f"Your code: {code}")
                await sync_to_async(request.session.__setitem__)('unverified_user_id', user.id)

                if is_json_request(request):
                    return JsonResponse({'status': 'success', 'email': user.email}, status=201)

                messages.success(request, f"Code sent to {user.email}")
                return redirect('verify_registration')

            except services.ServiceError as e:
                if is_json_request(request): return JsonResponse({'error': str(e)}, status=400)
                messages.error(request, str(e))
        else:
            messages.error(request, "Please check the form.")
    else:
        form = SignUpForm()
    
    return await sync_to_async(render)(request, 'tracker/register.html', {'form': form})

async def verify_registration(request):
    # 1. Get the ID stored in the session
    user_id = await sync_to_async(request.session.get)('unverified_user_id')
    
    # If no ID, kick them out
    if not user_id and not is_json_request(request):
        return redirect('register')

    # 2. Fetch the actual User object to get their email
    try:
        user_obj = await User.objects.aget(pk=user_id)
        user_email = user_obj.email
    except User.DoesNotExist:
        # If user was deleted (e.g. by our cleanup logic), restart
        await sync_to_async(request.session.flush)()
        return redirect('register')

    if request.method == 'POST':
        code = request.POST.get('code')
        try:
            dto = schemas.VerifyCodeDTO(user_id=user_id, code=code)
            success, msg = await services.verify_code(dto, acting_user_id=user_id)

            if is_json_request(request):
                return JsonResponse({'status': 'success', 'message': msg})

            if success:
                messages.success(request, msg)
                await sync_to_async(request.session.pop)('unverified_user_id')
                return redirect('login')

        except services.ServiceError as e:
            if is_json_request(request): return JsonResponse({'error': str(e)}, status=400)
            messages.error(request, str(e))

    return await sync_to_async(render)(request, 'tracker/verify_registration.html', {'email': user_email})

async def resend_code(request):
    user_id = await sync_to_async(request.session.get)('unverified_user_id')
    if not user_id: return redirect('register')
    
    try:
        dto = schemas.ResendCodeDTO(user_id=user_id)
        success, code, email = await services.resend_code(dto)
        send_email_task.delay(email, "New Code", f"Your code: {code}")
        
        if is_json_request(request): return JsonResponse({'status': 'sent'})
        messages.success(request, "Code resent.")
        
    except Exception as e:
        messages.error(request, str(e))
        
    return redirect('verify_registration')

async def verify_email_change(request):
    # USE request.auser() FOR ASYNC SAFETY
    user = await request.auser()
    if not user.is_authenticated: return redirect('login')

    if request.method == 'POST':
        code = request.POST.get('code')
        try:
            dto = schemas.VerifyEmailChangeDTO(user_id=user.id, code=code)
            success, msg = await services.verify_email_change(dto)
            if is_json_request(request): return JsonResponse({'status': 'success'})
            messages.success(request, msg)
            return redirect('profile')
        except Exception as e:
            if is_json_request(request): return JsonResponse({'error': str(e)}, status=400)
            messages.error(request, str(e))
    return await sync_to_async(render)(request, 'tracker/verify_email_change.html')

async def password_change_view(request):
    # USE request.auser() FOR ASYNC SAFETY
    user = await request.auser()
    if not user.is_authenticated: return redirect('login')

    if request.method == 'POST':
        try:
            dto = schemas.PasswordChangeDTO(
                old_password=request.POST.get('old_password'),
                new_password=request.POST.get('new_password1')
            )
            success, msg = await services.change_password(user, dto)
            # Session updates must also be wrapped
            await sync_to_async(update_session_auth_hash)(request, user)
            
            if is_json_request(request): return JsonResponse({'status': 'success'})
            messages.success(request, msg)
            return redirect('password_change_done')
        except Exception as e:
            messages.error(request, str(e))
    return await sync_to_async(render)(request, 'tracker/password_change_form.html')

async def delete_account_view(request):
    # USE request.auser() FOR ASYNC SAFETY
    user = await request.auser()
    if not user.is_authenticated: return redirect('login')

    if request.method == 'POST':
        try:
            dto = schemas.DeleteAccountDTO(user_id=user.id, password=request.POST.get('password'))
            await services.delete_account(dto)
            await sync_to_async(logout)(request)
            if is_json_request(request): return JsonResponse({'status': 'deleted'})
            messages.info(request, "Account deleted.")
            return redirect('register')
        except Exception as e:
            messages.error(request, str(e))
    return await sync_to_async(render)(request, 'tracker/delete_account.html')

async def update_location_view(request):
    # USE request.auser() FOR ASYNC SAFETY
    user = await request.auser()
    if not user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    if request.method == 'POST':
        try:
            body = json.loads(request.body)
            dto = schemas.UpdateLocationDTO(latitude=body.get('latitude'), longitude=body.get('longitude'))
            success, msg = await services.update_user_location(user.id, dto)
            return JsonResponse({'status': 'success', 'message': msg})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

async def logout_view(request):
    await sync_to_async(logout)(request)
    if is_json_request(request): return JsonResponse({'status': 'logged_out'})
    return redirect('login')

async def cancel_registration(request):
    uid = await sync_to_async(request.session.get)('unverified_user_id')
    if uid:
        try:
            u = await User.objects.aget(id=uid)
            if not u.is_active: await u.adelete()
            await sync_to_async(request.session.pop)('unverified_user_id')
        except: pass
    return redirect('register')

# ==========================================
#  SECTION 2: SYNC BUSINESS LOGIC
#  (Dashboard, Goals, Transactions)
# ==========================================

@login_required(login_url='login')
def dashboard(request):
    current_month = timezone.now().month
    current_year = timezone.now().year
    user = request.user
    
    goals = BudgetGoal.objects.filter(
        user=user, month=current_month, year=current_year
    )
    
    expense_qs = Transaction.objects.filter(
        user=user, type='Expense', date__month=current_month, date__year=current_year
    ).values('category').annotate(total=Sum('amount'))

    expense_map = {i['category']: i['total'] for i in expense_qs}
    goal_progress = []

    for goal in goals:
        spent = expense_map.get(goal.category, Decimal('0.00'))
        target = float(goal.target_amount)
        spent_amt = float(spent)
        percent = (spent_amt / target) * 100 if target > 0 else 0
        goal_progress.append({
            'pk': goal.pk, 'category': goal.category.title(),
            'target': target, 'spent': spent, 'percent': round(percent, 1),
            'status': 'exceeded' if percent > 100 else ('warning' if percent >= 80 else 'ok')
        })

    all_transactions = Transaction.objects.filter(user=user)
    totals = all_transactions.aggregate(
        income=Sum('amount', filter=Q(type__iexact='Income')),
        expense=Sum('amount', filter=Q(type__iexact='Expense'))
    )
    total_income = totals['income'] or Decimal('0.0')
    total_expense = totals['expense'] or Decimal('0.0')
    balance = total_income - total_expense

    if is_json_request(request):
        return JsonResponse({
            'status': 'success',
            'data': {
                'current_month': current_month, 'current_year': current_year,
                'total_income': float(total_income), 'total_expense': float(total_expense),
                'balance': float(balance), 'goal_progress': goal_progress,
                'transactions': list(all_transactions.values('id', 'amount', 'type', 'category', 'date')[:5])
            }
        })
    return render(request, "tracker/dashboard.html", {
        'current_month': current_month, 'current_year': current_year,
        "total_income": total_income, "total_expense": total_expense, "balance": balance,
        'goal_progress': goal_progress, "transactions": all_transactions[:5],
    })

@login_required(login_url='login')
def transaction_list(request):
    user = request.user
    transaction_categories = Transaction.objects.filter(user=user).values_list('category', flat=True)
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
            messages.warning(request, "Invalid date format.")

    query = request.GET.get('q')
    if query:
        all_transactions = all_transactions.filter(Q(description__icontains=query) | Q(category__icontains=query))

    paginator = Paginator(all_transactions, 20)
    page_number = request.GET.get('page')
    try:
        transactions_page = paginator.page(page_number)
    except PageNotAnInteger:
        transactions_page = paginator.page(1)
    except EmptyPage:
        transactions_page = paginator.page(paginator.num_pages)

    total_income = all_transactions.filter(type='Income').aggregate(Sum('amount'))['amount__sum'] or 0
    total_expense = all_transactions.filter(type='Expense').aggregate(Sum('amount'))['amount__sum'] or 0   

    if is_json_request(request):
        return JsonResponse({'status': 'success', 'data': list(transactions_page.object_list.values())})

    MASTER_TRANSACTION_CATEGORIES = [choice[0] for choice in Transaction._meta.get_field('category').choices]
    
    return render(request, 'tracker/transaction_list.html', {
        'transactions': transactions_page,
        'categories': MASTER_TRANSACTION_CATEGORIES,
        'current_query': query,
        'total_income_period': total_income,
        'total_expense_period': total_expense,
        'total_balance_period': total_income - total_expense
    })

@login_required(login_url='login')
def add_transaction(request):
    user = request.user
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount'))
            Transaction.objects.create(
                user=user,
                type=request.POST.get('type'),
                amount=amount,
                category=request.POST.get('category'),
                description=request.POST.get('description'),
                date=request.POST.get('date')
            )
            if is_json_request(request): return JsonResponse({'status': 'success', 'message': 'Transaction added'}, status=201)
            messages.success(request, "Transaction added successfully!")
            return redirect('transactions')
        except Exception as e:
            if is_json_request(request): return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, f"Failed to add: {e}")
            return redirect('add_transaction')
            
    return render(request, 'tracker/add_transaction.html', {'categories': Transaction.CATEGORY_CHOICES})

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
            if is_json_request(request): return JsonResponse({'status': 'success'})
            messages.success(request, 'Transaction updated.')
            return redirect("transactions")
        except Exception as e:
            if is_json_request(request): return JsonResponse({'error': str(e)}, status=400)
            messages.error(request, str(e))
    return render(request, "tracker/editTransaction.html", {"transaction": transaction})

@login_required(login_url='login')
def delete_transaction(request, pk):
    transaction = Transaction.objects.filter(pk=pk, user=request.user).first()
    if not transaction:
        if is_json_request(request): return JsonResponse({'error': 'Not Found'}, status=404)
        return render(request, '404.html', status=404)

    if request.method in ["DELETE", "POST"]:
        transaction.delete()
        if is_json_request(request): return JsonResponse({'status': 'success', 'message': 'Deleted'})
        messages.success(request, 'Transaction deleted.')
        return redirect('transactions')
    return render(request, 'tracker/delete_confirm.html', {'transaction': transaction})

@login_required(login_url='login')
def charts(request):
    transactions = Transaction.objects.filter(user=request.user)
    total_income = 0.0
    total_expense = 0.0
    category_totals = defaultdict(float)

    for t in transactions:
        try:
            amount = float(t.amount)
            if t.type == "Income": total_income += amount
            elif t.type == "Expense":
                total_expense += amount
                category_totals[t.category] += amount
        except: continue

    balance = total_income - total_expense
    context = {
        "total_income": total_income, "total_expense": total_expense, "balance": balance,
        "category_labels": list(category_totals.keys()),
        "category_values": list(category_totals.values()),
    }
    if is_json_request(request): return JsonResponse({'status': 'success', 'data': context})
    return render(request, "tracker/charts.html", context)

@login_required(login_url='login')
def goals_list(request, year=None, month=None):
    user = request.user
    now = timezone.now()
    categories = Transaction.CATEGORY_CHOICES
    view_month = int(month or request.GET.get('month') or now.month)
    view_year = int(year or request.GET.get('year') or now.year)

    current_goals = BudgetGoal.objects.filter(user=user, year=view_year, month=view_month).order_by('category')
    
    is_history = (view_year < now.year) or (view_year == now.year and view_month < now.month)
    can_import = not is_history and not current_goals.exists()

    expense_totals = Transaction.objects.filter(
        user=user, type='Expense', date__year=view_year, date__month=view_month
    ).values('category').annotate(total=Sum('amount'))
    
    expense_map = {item['category']: item['total'] for item in expense_totals}

    goals_data = []
    for goal in current_goals:
        spent = expense_map.get(goal.category, Decimal('0.00'))
        goal.actual_spent = spent
        goal.remaining = goal.target_amount - spent
        if goal.target_amount > 0:
            goal.progress_percent = min((float(spent) / float(goal.target_amount)) * 100, 100)
        else:
            goal.progress_percent = 0
        
        goal.is_over_budget = goal.remaining < 0
        
        goals_data.append({
            'id': goal.id, 'category': goal.category, 'target': float(goal.target_amount),
            'spent': float(spent), 'remaining': float(goal.remaining)
        })

    if is_json_request(request):
        return JsonResponse({'status': 'success', 'data': goals_data})

    return render(request, 'tracker/goals_list.html', {
        'goals': current_goals, 'categories': categories,
        'view_month': datetime(view_year, view_month, 1), 
        'view_year': view_year,
        'months_choices': [(i, datetime(2000, i, 1).strftime('%B')) for i in range(1, 13)],
        'year_choices': [now.year, now.year-1, now.year-2],
        'is_history': is_history, 'can_import': can_import,
    })

@login_required(login_url='login')
def set_goals(request):
    user = request.user
    if request.method == 'POST':
        category = request.POST.get('category')
        try:
            target = Decimal(request.POST.get('target_amount'))
            BudgetGoal.objects.update_or_create(
                user=user, category=category, month=timezone.now().month, year=timezone.now().year,
                defaults={'target_amount': target}
            )
            BudgetLock.objects.filter(user=user, month=timezone.now().month, year=timezone.now().year).delete()

            if is_json_request(request): return JsonResponse({'status': 'success'})
            messages.success(request, f'Goal set for {category}.')
        except Exception as e:
            if is_json_request(request): return JsonResponse({'error': str(e)}, status=400)
            messages.error(request, str(e))
    return redirect('goals_list')

@login_required(login_url='login')
def edit_goal(request, pk):
    goal = get_object_or_404(BudgetGoal, pk=pk, user=request.user)
    if request.method == 'POST':
        form = BudgetGoalForm(request.POST, instance=goal, user=request.user)
        if form.is_valid():
            form.save()
            if is_json_request(request): return JsonResponse({'status': 'success'})
            messages.success(request, "Goal updated.")
            return redirect('goals_list')
        elif is_json_request(request): return JsonResponse({'errors': form.errors}, status=400)
    else:
        form = BudgetGoalForm(instance=goal, user=request.user)
    return render(request, 'tracker/edit_goal.html', {'form': form, 'goal': goal})

@login_required(login_url='login')
def delete_goal(request, pk):
    goal = get_object_or_404(BudgetGoal, pk=pk, user=request.user)
    if request.method in ["POST", "DELETE"]:
        goal.delete()
        if is_json_request(request): return JsonResponse({'status': 'deleted'})
        messages.success(request, "Goal deleted.")
        return redirect('goals_list')
    return render(request, 'tracker/delete_goal.html', {'goal': goal})

@login_required(login_url='login')
def clear_monthly_goals(request, year, month):
    now = timezone.now()
    if year < now.year or (year == now.year and month < now.month):
        return JsonResponse({'status': 'error', 'message': 'Cannot clear past goals.'}, status=403)
    
    count, _ = BudgetGoal.objects.filter(user=request.user, year=year, month=month).delete()
    BudgetLock.objects.get_or_create(user=request.user, year=year, month=month) 

    if is_json_request(request): return JsonResponse({'status': 'success', 'deleted': count})
    messages.warning(request, f"Cleared {count} goals.")
    return redirect(reverse('goals_list') + f"?year={year}&month={month}")

@login_required(login_url='login')
def import_previous_goals(request):
    user = request.user
    view_month = int(request.GET.get('month', timezone.now().month))
    view_year = int(request.GET.get('year', timezone.now().year))

    latest_record = BudgetGoal.objects.filter(user=user).exclude(month=view_month, year=view_year).order_by('-year', '-month').first()

    if latest_record:
        template_goals = BudgetGoal.objects.filter(user=user, month=latest_record.month, year=latest_record.year)
        BudgetGoal.objects.filter(user=user, month=view_month, year=view_year).delete()
        new_goals = [
            BudgetGoal(user=user, category=g.category, target_amount=g.target_amount, month=view_month, year=view_year)
            for g in template_goals
        ]
        BudgetGoal.objects.bulk_create(new_goals)
        BudgetLock.objects.filter(user=user, month=view_month, year=view_year).delete()

        if is_json_request(request): return JsonResponse({'status': 'success'})
        messages.success(request, "Goals imported.")
    else:
        messages.warning(request, "No previous goals found.")

    return redirect(reverse('goals_list') + f"?year={view_year}&month={view_month}")

@login_required(login_url='login')
def change_currency(request):
    if request.method == 'POST':
        currency_code = request.POST.get('currency_code')
        try:
            profile = request.user.userprofile
            profile.currency_code = currency_code
            profile.save()
            messages.success(request, f"Currency changed to {currency_code}")
        except:
            UserProfile.objects.create(user=request.user, currency_code=currency_code)
        
        if is_json_request(request): return JsonResponse({'status': 'success', 'currency': currency_code})
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required(login_url='login')
def profile_settings(request):
    if request.method == 'POST':
        if 'request_email_change' in request.POST:
            try:
                dto = schemas.EmailChangeRequestDTO(user_id=request.user.id, new_email=request.POST.get('email'))
                # Redirect to async verify
                return redirect('verify_email_change') 
            except Exception as e:
                messages.error(request, str(e))
        else:
            form = ProfileUpdateForm(request.POST, instance=request.user)
            if form.is_valid():
                form.save()
                if is_json_request(request): return JsonResponse({'status': 'updated'})
                messages.success(request, 'Profile updated.')
    else:
        form = ProfileUpdateForm(instance=request.user)

    return render(request, 'tracker/profile_settings.html', {'form': form, 'profile': request.user.userprofile})

@login_required
def resend_verification_code(request):
    profile = request.user.userprofile
    if not profile.pending_email or not profile.email_verification_code:
        messages.error(request, "No pending email change found.")
        return redirect('profile')

    html_content = f"""
        <p>You requested to change your email address.</p>
        <p>Your verification code is: <strong>{profile.email_verification_code}</strong></p>
    """
    send_email_task.delay(profile.pending_email, "Verify Your New Email", html_content)
    messages.success(request, f"Code resent to {profile.pending_email}")
    return redirect('verify_email_change')

# ==========================================
#  ERROR HANDLERS
# ==========================================
def password_change_done_custom(request):
    return render(request, 'tracker/password_change_done.html')

def custom_403_handler(request, exception=None):
    if is_json_request(request): return JsonResponse({'error': 'Forbidden'}, status=403)
    return render(request, 'errors/403.html', status=403)

def custom_404_handler(request, exception):
    if is_json_request(request): return JsonResponse({'error': 'Not Found'}, status=404)
    return render(request, 'errors/404.html', status=404)

def custom_500_handler(request):
    if is_json_request(request): return JsonResponse({'error': 'Server Error'}, status=500)
    return render(request, 'errors/500.html', status=500)

def csrf_failure_json(request, reason=""):
    return JsonResponse({'status': 'error', 'message': f'CSRF Failure: {reason}'}, status=403)
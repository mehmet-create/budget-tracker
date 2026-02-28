import json
import csv
import io
import re
import codecs
import logging
from .ai_services import audit_subscriptions_stream

import os
import uuid
from .utils import send_async_email
from datetime import datetime, timedelta
from collections import defaultdict
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, update_session_auth_hash, get_user_model
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth import views as auth_views
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.core.cache import cache
from django.db.models import Sum, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf import settings
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.core.files.storage import default_storage
from django.db import transaction
from .models import Transaction, BudgetGoal, UserProfile, BudgetLock
from .forms import SignUpForm, BudgetGoalForm, ProfileUpdateForm, TransactionForm, CSVUploadForm, CustomPasswordResetForm
from . import services, schemas
from .ratelimit import check_ratelimit, RateLimitError
from .ai_services import scan_receipt
from .ai_services import audit_subscriptions
from openpyxl import load_workbook


logger = logging.getLogger(__name__)
User = get_user_model()


@require_http_methods(["GET", "POST", "HEAD"])
def health(request):
    """Health check endpoint for uptime monitoring. Allows GET, POST, HEAD."""
    return JsonResponse({'status': 'ok'})

def get_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    return x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')

def is_json_request(request):
    accept = request.headers.get('Accept', '')
    return 'application/json' in accept and 'text/html' not in accept


def login_view(request):
    ip = get_ip(request)

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        # Composite key: blocks IP+username pair — only on POST, never on GET
        ratelimit_key = f"login_fail_{ip}_{username}" if username else f"login_fail_{ip}"
        try:
            check_ratelimit(ratelimit_key, limit=10, period=60)
        except RateLimitError as e:
            if is_json_request(request):
                return JsonResponse({'error': str(e)}, status=429)
            messages.error(request, str(e))
            return render(request, 'tracker/login.html')
    else:
        ratelimit_key = f"login_fail_{ip}"

    if request.method == 'POST':
        dto = schemas.LoginDTO(
            username=username,
            password=request.POST.get('password')
        )
        user, status = services.login_service(request, dto)

        if status == "success":
            login(request, user)
            cache.delete(f"ratelimit:{ratelimit_key}")
            
            if is_json_request(request):
                return JsonResponse({'status': 'success', 'user': user.username})
            return redirect('dashboard')

        else:
            attempts_used = cache.get(f"ratelimit:{ratelimit_key}", 0)
            if not isinstance(attempts_used, int):
                attempts_used = 0
            remaining = max(0, 10 - attempts_used)
            
            error_msg = "Invalid credentials."
            if status == "unverified":
                error_msg = "Account not verified."
            
            if remaining <= 3 and remaining > 0:
                error_msg += f" Warning: {remaining} attempts remaining."
            
            if is_json_request(request):
                return JsonResponse({'status': 'error', 'code': status, 'message': error_msg}, status=401)

            messages.error(request, error_msg)
            
            if status == "unverified":
                request.session['unverified_user_id'] = user.id
                return redirect('verify_registration')

    return render(request, 'tracker/login.html')


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.method == 'POST':
        try:
            check_ratelimit(f"reg_ip_{get_ip(request)}", limit=50, period=3600)
        except RateLimitError as e:
            if is_json_request(request): 
                return JsonResponse({'status': 'error', 'message': str(e)}, status=429)
            messages.error(request, str(e))
            return redirect('login')

    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
        else:
            data = request.POST
        
        form = SignUpForm(data)
        
        if form.is_valid():
            try:
                dto = schemas.RegisterDTO(
                    username=form.cleaned_data['username'],
                    email=form.cleaned_data['email'],
                    password=form.cleaned_data['password'],
                    first_name=form.cleaned_data.get('first_name', ''),
                    last_name=form.cleaned_data.get('last_name', '')
                )
                
                user, code = services.register_user(dto)
                
                send_async_email(user.email, "Verification Code", f"Your code: {code}")
                request.session['unverified_user_id'] = user.id

                if is_json_request(request):
                    return JsonResponse({
                        'status': 'success', 
                        'message': 'User registered successfully. Check email for code.',
                        'email': user.email
                    }, status=201)

                messages.success(request, f"Code sent to {user.email}")
                return redirect('verify_registration')

            except services.ServiceError as e:
                if is_json_request(request): 
                    return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
                messages.error(request, str(e))
        else:
            if is_json_request(request):
                return JsonResponse({
                    'status': 'error',
                    'message': 'Validation failed',
                    'errors': form.errors
                }, status=400)
            messages.error(request, "Please check the form.")

    else:
        if is_json_request(request):
            return JsonResponse({
                'status': 'success',
                'message': 'Register endpoint ready.',
                'method': 'POST'
            })
        form = SignUpForm()
    
    return render(request, 'tracker/register.html', {'form': form})


@require_http_methods(["GET", "POST"])
def verify_registration(request):
    user_id = request.session.get('unverified_user_id')
    
    if not user_id:
        if is_json_request(request):
            return JsonResponse({
                'status': 'error', 
                'message': 'No registration session found. Please register first.'
            }, status=401)
        return redirect('register')

    try:
        user_obj = User.objects.get(pk=user_id)
        user_email = user_obj.email
    except User.DoesNotExist:
        request.session.flush()
        
        if is_json_request(request):
            return JsonResponse({'status': 'error', 'message': 'User not found. Register again.'}, status=404)
            
        return redirect('register')

    if request.method == 'POST':
        code = request.POST.get('code')
        try:
            dto = schemas.VerifyCodeDTO(user_id=user_id, code=code)
            success, msg = services.verify_code(dto, acting_user_id=user_id)

            if is_json_request(request):
                return JsonResponse({'status': 'success', 'message': msg})

            if success:
                messages.success(request, msg)
                request.session.pop('unverified_user_id', None)
                return redirect('login')

        except services.ServiceError as e:
            if is_json_request(request): 
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, str(e))

    if is_json_request(request):
        return JsonResponse({
            'status': 'success',
            'message': 'Verification endpoint ready.',
            'email_to_verify': user_email,
            'required_fields': ['code']
        })

    return render(request, 'tracker/verify_registration.html', {'email': user_email})


@require_http_methods(["GET", "POST"])
def resend_code(request):
    user_id = request.session.get('unverified_user_id')
    
    if not user_id:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': 'Session expired. Register again.'}, status=401)
        return redirect('register')
    
    if request.method == "GET" and is_json_request(request):
        return JsonResponse({'status': 'ready', 'message': 'Send POST to resend code.'})

    cache_key = f"resend_code_cooldown_{user_id}"
    if cache.get(cache_key):
        msg = "Please wait a minute before requesting another code."
        if is_json_request(request):
            return JsonResponse({'status': 'error', 'message': msg}, status=429)
        messages.warning(request, msg)
        return redirect('verify_registration')

    try:
        dto = schemas.ResendCodeDTO(user_id=user_id)
        # Sync Service Call
        success, code, email = services.resend_code(dto)
        send_async_email(email, "New Code", f"Your code: {code}")

        cache.set(cache_key, True, 60)
        
        if is_json_request(request): 
            return JsonResponse({'status': 'success', 'message': 'Code resent'})
        
        messages.success(request, "Code resent.")
        
    except Exception as e:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        messages.error(request, str(e))
        
    return redirect('verify_registration')


@require_http_methods(["GET", "POST"])
def verify_email_change(request):
    user = request.user
    
    if not user.is_authenticated:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    if request.method == 'POST':
        code = None
        if request.POST:
            code = request.POST.get('code')

        if not code:
            try:
                if request.body:
                    data = json.loads(request.body)
                    code = data.get('code')
            except json.JSONDecodeError:
                pass    
        try:
            dto = schemas.VerifyEmailChangeDTO(user_id=user.id, code=code)
            success, msg = services.verify_email_change(dto)
            
            if success:
                if is_json_request(request):
                    return JsonResponse({'status': 'success', 'message': msg})
            
                messages.success(request, msg)
                return redirect('profile')
            else:
                if is_json_request(request):
                    return JsonResponse({'status': 'error', 'message': msg}, status=400)
                messages.error(request, msg)
                return redirect('verify_email_change')
        except Exception as e:
            if is_json_request(request): 
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, str(e))
            return redirect('verify_email_change')

    if is_json_request(request):
        return JsonResponse({
            'status': 'ready', 
            'message': 'Send POST with "code" to verify email change.'
        })

    return render(request, 'tracker/verify_email_change.html')


@require_http_methods(["GET", "POST"])
def password_change_view(request):
    user = request.user
    
    if not user.is_authenticated:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    if request.method == 'POST':
        data = {}
        if request.POST:
            data = request.POST

        else:
            try:
                if request.body:
                    data = json.loads(request.body)
            except json.JSONDecodeError:
                pass
        try:
            dto = schemas.PasswordChangeDTO(
                user_id=user.id,
                old_password=data.get('old_password'),
                new_password=data.get('new_password1'),
                confirm_new_password=data.get('new_password2')
            )
            success, msg = services.change_password(request.user, dto)
            if success:
                # refresh_from_db() ensures the session hash reflects the NEW password
                request.user.refresh_from_db()
                update_session_auth_hash(request, request.user)
                
                if is_json_request(request): 
                    return JsonResponse({'status': 'success', 'message': msg})
                
                messages.success(request, msg)
                return redirect('password_change_done')
            
            else:
                raise ValueError(msg)
        except ValueError as e:
            if is_json_request(request): 
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, str(e))            

    if is_json_request(request):
        return JsonResponse({
            'status': 'ready', 
            'required_fields': ['old_password', 'new_password', 'confirm_new_password']
        })

    return render(request, 'tracker/password_change_form.html')


@require_http_methods(["GET", "POST", "DELETE"])
def delete_account_view(request):
    user = request.user
    
    if not user.is_authenticated:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    if request.method == 'POST':
        try:
            dto = schemas.DeleteAccountDTO(user_id=user.id, password=request.POST.get('password'))
            services.delete_account(dto)
            logout(request)
            
            if is_json_request(request): 
                return JsonResponse({'status': 'success', 'message': 'Account deleted'})
            
            messages.info(request, "Account deleted.")
            return redirect('register')
            
        except Exception as e:
            if is_json_request(request): 
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            messages.error(request, str(e))

    if is_json_request(request):
        return JsonResponse({
            'status': 'warning', 
            'message': 'Send POST with "password" to PERMANENTLY delete account.'
        })

    return render(request, 'tracker/delete_account.html')


@require_POST
def logout_view(request):
    logout(request)
    if is_json_request(request): return JsonResponse({'status': 'logged_out'})
    return redirect('login')


@require_POST
def cancel_registration(request):
    uid = request.session.get('unverified_user_id')
    if uid:
        try:
            u = User.objects.get(id=uid)
            if not u.is_active: 
                u.delete()
            request.session.pop('unverified_user_id', None)
        except User.DoesNotExist: 
            pass
    return redirect('register')

class CustomPasswordResetView(PasswordResetView):
    email_template_name = 'tracker/password_reset_email.html'
    subject_template_name = 'tracker/password_reset_subject.txt'
    from_email = settings.DEFAULT_FROM_EMAIL
    form_class = CustomPasswordResetForm

    def dispatch(self, request, *args, **kwargs):
        # Rate limit: 5 password reset attempts per hour per IP
        ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', '')
        try:
            check_ratelimit(f"pwd_reset_{ip}", limit=5, period=3600)
        except RateLimitError as e:
            if is_json_request(request):
                return JsonResponse({'status': 'error', 'message': str(e)}, status=429)
            messages.error(request, str(e))
            return redirect('password_reset')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Form is valid — custom form.save() handles email via Resend HTTP API."""
        try:
            form.save(
                domain_override=self.request.get_host(),
                subject_template_name=self.subject_template_name,
                email_template_name=self.email_template_name,
                use_https=self.request.is_secure(),
                from_email=self.from_email,
                request=self.request,
            )
        except Exception as exc:
            logger.exception("Password reset form.save() failed: %s", exc)
            if is_json_request(self.request):
                return JsonResponse({
                    'status': 'error',
                    'message': 'Could not send reset email. Please try again shortly.'
                }, status=503)
            messages.error(self.request, 'Could not send reset email. Please try again shortly.')
            return redirect('password_reset')

        if is_json_request(self.request):
            return JsonResponse({
                'status': 'success',
                'message': 'Password reset instructions have been sent to your email.'
            })

        from django.http import HttpResponseRedirect
        from django.urls import reverse
        return HttpResponseRedirect(reverse('password_reset_done'))

    def form_invalid(self, form):
        if is_json_request(self.request):
            return JsonResponse({
                'status': 'error',
                'errors': form.errors
            }, status=400)
            
        return super().form_invalid(form)

class CustomPasswordResetDoneView(auth_views.PasswordResetDoneView):
    def get(self, request, *args, **kwargs):
        if is_json_request(request):
            return JsonResponse({
                'status': 'success',
                'message': 'Password reset instructions have been sent to your email.'
            })
        return super().get(request, *args, **kwargs)
class CustomPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    def _wants_json(self, request):
        return is_json_request(request) or request.GET.get('format') == 'json'

    def dispatch(self, request, *args, **kwargs):
        if self._wants_json(request):
            return password_reset_confirm_api(request, kwargs.get('uidb64'), kwargs.get('token'))

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        if self._wants_json(request):
            return password_reset_confirm_api(request, kwargs.get('uidb64'), kwargs.get('token'))

        # The parent 'dispatch' method already checked the token and set self.validlink
        response = super().get(request, *args, **kwargs)
        return response

    def post(self, request, *args, **kwargs):
        if self._wants_json(request):
            return password_reset_confirm_api(request, kwargs.get('uidb64'), kwargs.get('token'))

        # 1. CHECK LINK VALIDITY FIRST
        # self.validlink is set automatically by Django before this method runs
        if not self.validlink:
            if self._wants_json(request):
                return JsonResponse({
                    'status': 'error', 
                    'message': 'The password reset link is invalid or has expired.'
                }, status=400)
        
        # 2. Proceed with standard Django logic
        # This will call get_form(), form_valid(), or form_invalid()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        form.save()
        if self._wants_json(self.request):
            return JsonResponse({
                'status': 'success', 
                'message': 'Password has been reset successfully.'
            })
        return super().form_valid(form)

    def form_invalid(self, form):
        # This catches missing fields (like missing new_password1)
        if self._wants_json(self.request):
            return JsonResponse({
                'status': 'error', 
                'errors': form.errors
            }, status=400)
        return super().form_invalid(form)


@require_http_methods(["GET", "POST"])
def password_reset_confirm_api(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = get_user_model().objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return JsonResponse({'status': 'error', 'message': 'Invalid user.'}, status=400)

    if not PasswordResetTokenGenerator().check_token(user, token):
        return JsonResponse({
            'status': 'error',
            'message': 'Password reset link is invalid or has expired.'
        }, status=400)

    if request.method == "GET":
        return JsonResponse({
            'status': 'success',
            'message': 'Token is valid.',
            'action': 'Submit POST with "new_password1" and "new_password2"'
        })

    data = request.POST
    if not data:
        try:
            if request.body:
                data = json.loads(request.body)
        except json.JSONDecodeError:
            data = {}

    form = SetPasswordForm(user, data=data)
    if form.is_valid():
        form.save()
        return JsonResponse({
            'status': 'success',
            'message': 'Password has been reset successfully.'
        })

    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

class CustomPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    def get(self, request, *args, **kwargs):
        if is_json_request(request):
            return JsonResponse({
                'status': 'success',
                'message': 'Password reset complete. You may now log in.'
            })
        return super().get(request, *args, **kwargs)

@login_required
@require_GET
def dashboard(request):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    now = timezone.now()
    current_month = now.month
    current_year = now.year
    
    goals = BudgetGoal.objects.filter(user=user, month=current_month, year=current_year)
    

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
        target = goal.target_amount
        
        goal.actual_spent = spent
        goal.progress_percent = (spent / target) * 100 if target > 0 else 0
        goal.remaining = target - spent
        
        if target > 0:
            goal.percent = min(int((spent / target) * 100), 100)
            real_percent = (spent / target) * 100 
        else:
            goal.percent = 0
            real_percent = 0

        if real_percent > 100:
            goal.status = 'exceeded'
        elif real_percent >= 80:
            goal.status = 'warning'
        else:
            goal.status = 'good'
            
        goal_progress.append(goal)

    recent_transactions = Transaction.objects.filter(user=user).order_by('-date', '-id')[:5]

    all_transactions = Transaction.objects.filter(user=user)
    totals = all_transactions.aggregate(
        income=Sum('amount', filter=Q(type__iexact='Income')),
        expense=Sum('amount', filter=Q(type__iexact='Expense'))
    )
    
    total_income = totals['income'] or Decimal('0.00')
    total_expense = totals['expense'] or Decimal('0.00')
    balance = total_income - total_expense

    if is_json_request(request):
        json_goals = [{
            'category': g.get_category_display(),
            'target': float(g.target_amount),
            'spent': float(g.actual_spent),
            'percent': g.percent,
            'status': g.status
        } for g in goal_progress]
        
        json_trans = list(recent_transactions.values('id', 'amount', 'type', 'category', 'date'))
        
        return JsonResponse({
            'status': 'success',
            'data': {
                'current_month': current_month,
                'total_income': float(total_income),
                'total_expense': float(total_expense),
                'balance': float(balance),
                'goal_progress': json_goals,
                'transactions': json_trans
            }
        })

    context = {
        'recent_transactions': recent_transactions,
        'goals': goal_progress,
        'total_income': total_income,
        'total_expense': total_expense,
        'balance': balance,
        'current_month': now,
    }

    return render(request, "tracker/dashboard.html", context)

def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'tracker/landing.html')

def landing(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'tracker/landing.html')

@login_required
@require_GET
def transaction_list(request):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')
    
    all_transactions = Transaction.objects.filter(user=user).order_by('-date', '-id')

    query = request.GET.get('q') 
    category_filter = request.GET.get('category')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if query:
        all_transactions = all_transactions.filter(description__icontains=query)

    if category_filter and category_filter != 'All':
        all_transactions = all_transactions.filter(category=category_filter)

    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            if end_date:
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            else:
                # Default to today so a "from" date always gives a full range
                end_date_obj = datetime.today().date()
                end_date = end_date_obj.strftime('%Y-%m-%d')
            all_transactions = all_transactions.filter(date__range=[start_date_obj, end_date_obj])
        except ValueError:
            pass

    paginator = Paginator(all_transactions, 20)
    page_number = request.GET.get('page')
    try:
        transactions_page = paginator.page(page_number)
    except PageNotAnInteger:
        transactions_page = paginator.page(1)
    except EmptyPage:
        transactions_page = paginator.page(paginator.num_pages)

    income_agg = all_transactions.filter(type='Income').aggregate(Sum('amount'))
    expense_agg = all_transactions.filter(type='Expense').aggregate(Sum('amount'))
    total_income = income_agg['amount__sum'] or 0
    total_expense = expense_agg['amount__sum'] or 0

    if is_json_request(request):
        transactions_data = list(transactions_page.object_list.values(
            'id', 'date', 'description', 'amount', 'category', 'type'
        ))
        
        return JsonResponse({
            'status': 'success',
            'data': {
                'transactions': transactions_data,
                'pagination': {
                    'current_page': transactions_page.number,
                    'total_pages': paginator.num_pages,
                    'has_next': transactions_page.has_next(),
                    'has_previous': transactions_page.has_previous(),
                    'total_count': paginator.count
                },
                'totals': {
                    'income': float(total_income),
                    'expense': float(total_expense),
                    'balance': float(total_income - total_expense)
                },
                'filters': {
                    'query': query,
                    'category': category_filter,
                    'start_date': start_date,
                    'end_date': end_date
                }
            }
        })
    categories = Transaction.CATEGORY_CHOICES

    return render(request, 'tracker/transaction_list.html', {
        'transactions': transactions_page,
        'categories': categories,      
        'current_category': category_filter, 
        'current_query': query,        
        'current_start_date': start_date, 
        'current_end_date': end_date,   
        'total_income_period': total_income,
        'total_expense_period': total_expense,
        'total_balance_period': total_income - total_expense
    })

from . import schemas, services

@login_required
@require_http_methods(["GET", "POST"])
def add_transaction(request):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    if request.method == 'GET':
        if is_json_request(request): 
            return JsonResponse({'status': 'ready', 'required_fields': ['amount', 'type', 'category', 'date']})
        return render(request, 'tracker/add_transaction.html', {'form': TransactionForm()})

    if 'receipt_image' in request.FILES and 'amount' not in request.POST:
        ai_data = scan_receipt(request.FILES['receipt_image'])
        if ai_data:
            form = TransactionForm(initial=ai_data)
            messages.success(request, "Receipt scanned! Please review details.")
        else:
            form = TransactionForm()
            messages.error(request, "Could not read receipt.")
        return render(request, 'tracker/add_transaction.html', {'form': form})

    form = TransactionForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            dto = schemas.TransactionDTO(
                user_id=user.id,
                amount=form.cleaned_data['amount'],
                transaction_type=form.cleaned_data['type'],
                category=form.cleaned_data['category'],
                date=form.cleaned_data['date'],
                description=form.cleaned_data.get('description', ''),
            )
            
            services.create_transaction(dto)

            if is_json_request(request): 
                return JsonResponse({'status': 'success', 'message': 'Transaction added'}, status=201)
            
            messages.success(request, "Transaction added successfully!")
            return redirect('transactions')

        except Exception as e:
             if is_json_request(request): return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
             messages.error(request, f"Error: {e}")

    if is_json_request(request): 
        return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
    
    messages.error(request, "Please correct the errors below.")
    return render(request, 'tracker/add_transaction.html', {'form': form})


@login_required
@require_http_methods(["GET", "POST"])
def edit_transaction(request, pk):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    try:
        transaction = Transaction.objects.get(pk=pk, user=user)
    except Transaction.DoesNotExist:
        if is_json_request(request): return JsonResponse({'error': 'Not found'}, status=404)
        return render(request, '404.html', status=404)

    # Capture current page from referrer or query string for redirect
    page = request.GET.get('page')
    if not page and request.META.get('HTTP_REFERER'):
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(request.META['HTTP_REFERER'])
        page = parse_qs(parsed_url.query).get('page', [None])[0]

    if request.method == "POST":
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            dto = schemas.TransactionDTO(
                user_id=user.id,
                amount=form.cleaned_data['amount'],
                transaction_type=form.cleaned_data['type'],
                category=form.cleaned_data['category'],
                date=form.cleaned_data['date'],
                description=form.cleaned_data.get('description', '')
            )
            
            services.update_transaction(pk, dto)
            
            if is_json_request(request): return JsonResponse({'status': 'success', 'message': 'Updated'})
            messages.success(request, 'Transaction updated.')
            redirect_url = reverse('transactions')
            if page:
                redirect_url += f'?page={page}'
            return redirect(redirect_url)
        
        else:
            if is_json_request(request): return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)
            messages.error(request, "Please correct errors.")

    else:
        form = TransactionForm(instance=transaction)

    # Template removed — edits are done via modal on the list page
    return redirect("transactions")


@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def delete_transaction(request, pk):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')
    
    # Capture current page from referrer or query string for redirect
    page = request.GET.get('page')
    if not page and request.META.get('HTTP_REFERER'):
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(request.META['HTTP_REFERER'])
        page = parse_qs(parsed_url.query).get('page', [None])[0]
    
    if request.method in ["DELETE", "POST"]:
        try:
            services.delete_transaction(pk, user.id)
            if is_json_request(request): return JsonResponse({'status': 'success', 'message': 'Deleted'})
            messages.success(request, 'Transaction deleted.')
            redirect_url = reverse('transactions')
            if page:
                redirect_url += f'?page={page}'
            return redirect(redirect_url)
        except Exception:
            if is_json_request(request): return JsonResponse({'error': 'Not found'}, status=404)
            return render(request, '404.html', status=404)

    try:
        transaction = Transaction.objects.get(pk=pk, user=user)
    except Transaction.DoesNotExist:
         return render(request, '404.html', status=404)

    if is_json_request(request):
        return JsonResponse({'status': 'warning', 'message': 'Send DELETE/POST to confirm.'})
        
    # Template removed — deletions are done via modal on the list page
    return redirect('transactions')

def validate_file_extension(filename):
    if not filename.endswith(('.xlsx', '.csv')):
        raise ValueError("Invalid file type. Only .xlsx and .csv allowed.")
    
@login_required
@require_http_methods(["GET", "POST"])
def subscription_audit_view(request):
    user = request.user
    now  = timezone.now()

    # ── Resolve date range ────────────────────────────────────────
    start_date_str = (request.POST.get('start_date') or
                      request.GET.get('start_date') or
                      now.date().replace(day=1).strftime('%Y-%m-%d'))
    end_date_str   = (request.POST.get('end_date') or
                      request.GET.get('end_date') or
                      now.date().strftime('%Y-%m-%d'))

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date   = datetime.strptime(end_date_str,   '%Y-%m-%d').date()
    except ValueError:
        start_date = now.date().replace(day=1)
        end_date   = now.date()
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str   = end_date.strftime('%Y-%m-%d')

    # ── Pull real transactions from DB ────────────────────────────
    period_qs = (Transaction.objects
                 .filter(user=user, date__range=[start_date, end_date])
                 .order_by('date'))

    lines = []
    for t in period_qs:
        lines.append(
            f"{t.date}  {t.type:<8}  {t.get_category_display():<20}  "
            f"{(t.description or ''):<30}  {t.amount}"
        )
    pre_filled_text = '\n'.join(lines)

    # ── Goals for context ─────────────────────────────────────────
    goals = BudgetGoal.objects.filter(
        user=user,
        year__in=range(start_date.year, end_date.year + 1)
    )

    results   = None
    submitted = False
    error_msg = None

    # ── Run audit on POST ─────────────────────────────────────────
    if request.method == 'POST':
        submitted = True
        MAX_AUDIT_CHARS = 20_000  # ~5,000 transactions — prevents DoS/prompt injection
        db_text  = request.POST.get('transactions', '')[:MAX_AUDIT_CHARS].strip()
        csv_text = request.POST.get('csv_paste', '')[:MAX_AUDIT_CHARS].strip()

        csv_file = request.FILES.get('csv_file')
        if csv_file:
            try:
                csv_content = csv_file.read().decode('utf-8', errors='replace')
                csv_text = (csv_text + '\n' + csv_content).strip()
            except Exception:
                pass

        combined = '\n'.join(filter(None, [db_text, csv_text]))

        if combined:
            try:
                results = audit_subscriptions(combined, start_date_str, end_date_str)
                if results is None:
                    error_msg = "Tranasctions couldn't be analysed. Please check the format and try again."
            except Exception as e:
                logger.error(f"Audit error: {e}")
                error_msg = "Something went wrong running the audit. Please try again."
        else:
            error_msg = "No transaction data to analyse for the selected period."

    return render(request, 'tracker/audit.html', {
        'results':          results,
        'submitted':        submitted,
        'error_msg':        error_msg,
        'pre_filled_text':  pre_filled_text,
        'start_date':       start_date_str,
        'end_date':         end_date_str,
        'txn_count':        period_qs.count(),
        'goals':            goals,
    })

@login_required
@require_GET
def charts(request):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    transactions = list(Transaction.objects.filter(user=user))
    
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
    category_label_map = dict(Transaction.CATEGORY_CHOICES)
    category_labels = [category_label_map.get(key, key) for key in category_totals.keys()]
    context = {
        "total_income": total_income, "total_expense": total_expense, "balance": balance,
        "category_labels": category_labels,
        "category_values": list(category_totals.values()),
    }
    if is_json_request(request): return JsonResponse({'status': 'success', 'data': context})
    return render(request, "tracker/charts.html", context)

@login_required
@require_POST
def import_transactions(request):
    try:
        if 'file' not in request.FILES:
            raise ValueError("No file uploaded.")

        uploaded_file = request.FILES['file']

        # DTO validates size and extension
        dto = schemas.ImportTransactionsDTO(
            user_id=request.user.id,
            file=uploaded_file
        )

        # Call service directly — no Celery needed
        count = services.import_transactions_service(dto)

        msg = f"Successfully imported {count} transaction{'s' if count != 1 else ''}."
        if is_json_request(request):
            return JsonResponse({'status': 'ok', 'message': msg, 'count': count})
        messages.success(request, msg)

    except ValueError as e:
        if is_json_request(request):
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        messages.error(request, str(e))

    except Exception as e:
        if is_json_request(request):
            return JsonResponse({'status': 'error', 'message': 'An error occurred during import.'}, status=500)
        messages.error(request, "An error occurred during import. Check the file format and try again.")

    return redirect('transactions')
        
@login_required
@require_GET
def goals_list(request, year=None, month=None):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    now = timezone.now()
    
    form = BudgetGoalForm(user=user) 
    
    try:
        view_month = int(month or request.GET.get('month') or now.month)
        view_year = int(year or request.GET.get('year') or now.year)
    except ValueError:
        view_month = now.month
        view_year = now.year

    current_goals = list(
        BudgetGoal.objects.filter(user=user, year=view_year, month=view_month).order_by('category')
    )
    
    is_history = (view_year < now.year) or (view_year == now.year and view_month < now.month)
    can_import = not is_history and not current_goals


    expense_totals = list(
        Transaction.objects.filter(
            user=user, 
            type='Expense', 
            date__year=view_year, 
            date__month=view_month
        ).values('category').annotate(total=Sum('amount'))
    )
    
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
            'id': goal.id, 
            'category': goal.get_category_display(),
            'target': float(goal.target_amount),
            'spent': float(spent), 
            'remaining': float(goal.remaining)
        })

    if is_json_request(request):
        return JsonResponse({'status': 'success', 'data': goals_data})

    return render(request, 'tracker/goals_list.html', {
        'goals': current_goals, 
        'form': form,
        'view_month': datetime(view_year, view_month, 1), 
        'view_year': view_year,
        'months_choices': [(i, datetime(2000, i, 1).strftime('%B')) for i in range(1, 13)],
        'year_choices': [now.year, now.year-1, now.year-2],
        'is_history': is_history, 
        'can_import': can_import,
    })

@login_required
@require_POST
def set_goals(request):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    try:
        dto = schemas.SetGoalDTO(
            user_id=user.id,
            category=request.POST.get('category'),
            target_amount=request.POST.get('target_amount'),
            month=request.POST.get('month'),
            year=request.POST.get('year')
        )

        goal = services.set_budget_goal(dto)

        if is_json_request(request): 
            return JsonResponse({
                'status': 'success', 
                'message': f'Goal set for {dto.month}/{dto.year}',
                'data': {
                    'category': goal.category,
                    'target': float(goal.target_amount),
                    'month': goal.month,
                    'year': goal.year
                }
            })
        
        messages.success(request, f"Goal set for {dto.month}/{dto.year}.")
        return redirect(f'/goals/?month={dto.month}&year={dto.year}')

    except ValueError as e:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        messages.error(request, str(e))
        return redirect('goals_list')

@login_required
@require_http_methods(["GET", "POST"])
def edit_goal(request, pk):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    try:
        goal = BudgetGoal.objects.get(pk=pk, user=user)
    except BudgetGoal.DoesNotExist:
        return render(request, '404.html', status=404)

    if request.method == 'POST':
        form = BudgetGoalForm(request.POST, instance=goal)
        if form.is_valid():
            dto = schemas.UpdateGoalDTO(
                user_id=user.id,
                goal_id=pk,
                category=form.cleaned_data['category'],
                target_amount=form.cleaned_data['target_amount']
            )
            services.update_goal(dto)
            
            if is_json_request(request): return JsonResponse({'status': 'success'})
            messages.success(request, "Goal updated.")
            return redirect('goals_list')
    else:
        form = BudgetGoalForm(instance=goal)

    # Template removed — edits are done via modal on the goals page
    return redirect('goals_list')

@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def delete_goal(request, pk):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    try:
        goal = BudgetGoal.objects.get(pk=pk, user=user)
    except BudgetGoal.DoesNotExist:
        if is_json_request(request): return JsonResponse({'error': 'Goal not found'}, status=404)
        return render(request, '404.html', status=404)

    if request.method in ["POST", "DELETE"]:
        goal.delete()
        
        if is_json_request(request): return JsonResponse({'status': 'deleted'})
        messages.success(request, "Goal deleted.")
        return redirect('goals_list')

    if is_json_request(request):
        return JsonResponse({'status': 'warning', 'message': 'Send DELETE/POST to confirm.'})

    # Template removed — deletions are done via modal on the goals page
    return redirect('goals_list')


@require_POST
def clear_monthly_goals(request, year, month):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    now = timezone.now()
    year = int(year)
    month = int(month)

    if year < now.year or (year == now.year and month < now.month):
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Cannot clear past goals.'}, status=403)
        messages.warning(request, "Cannot clear past goals.")
        return redirect(reverse('goals_list') + f"?year={year}&month={month}")
    
    count, _ = BudgetGoal.objects.filter(user=user, year=year, month=month).delete()
    
    BudgetLock.objects.get_or_create(user=user, year=year, month=month)

    if is_json_request(request): return JsonResponse({'status': 'success', 'deleted': count})
    messages.warning(request, f"Cleared {count} goals.")
    return redirect(reverse('goals_list') + f"?year={year}&month={month}")

@require_POST
def import_previous_goals(request):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    try:
        month = int(request.POST.get('month') or timezone.now().month)
        year = int(request.POST.get('year') or timezone.now().year)

        dto = schemas.ImportGoalsDTO(
            user_id=user.id,
            target_month=month,
            target_year=year
        )
        
        services.import_previous_goals(dto)
        
        messages.success(request, "Goals imported successfully.")
        
    except (ValueError, services.ServiceError) as e:
        messages.warning(request, str(e))

    return redirect(f'/goals/?year={year}&month={month}')

@login_required
@require_POST
def change_currency(request):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    try:
        dto = schemas.UpdateCurrencyDTO(
            user_id=user.id,
            currency_code=request.POST.get('currency_code', '')
        )
        services.update_currency(dto)
        
        # Clear session cache so the new currency symbol is used
        request.session.pop('currency_symbol', None)

        if is_json_request(request):
            return JsonResponse({
                'status': 'success',
                'message': 'Currency updated.',
                'currency': dto.currency_code
            })

        messages.success(request, f"Currency changed to {dto.currency_code}")
        
    except ValueError as e:
        if is_json_request(request):
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        messages.error(request, str(e))
        
    # Never trust raw Referer — use Django URL reversing as fallback
    referer = request.META.get('HTTP_REFERER', '')
    from django.urls import reverse
    safe_fallback = reverse('dashboard')
    return redirect(referer if referer else safe_fallback)


@require_POST
def resend_verification_code_profile(request):
    user = request.user
    if not user.is_authenticated:
        if is_json_request(request): return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    cache_key = f"email_change_resend_cooldown_{user.id}"
    if cache.get(cache_key):
        msg = "Please wait a minute before requesting another code."
        if is_json_request(request):
            return JsonResponse({'status': 'error', 'message': msg}, status=429)
        messages.warning(request, msg)
        return redirect('verify_email_change')

    try:
        success, result = services.resend_email_change_code(user.id)

        if not success:
            if is_json_request(request): return JsonResponse({'status': 'error', 'message': result}, status=429)
            messages.warning(request, result)
            return redirect('verify_email_change')

        raw_code, email_to = result

        html_content = f"""
            <p>You requested a new verification code.</p>
            <p>Your code is: <strong>{raw_code}</strong></p>
        """
        send_async_email(email_to, "Your New Code", html_content)

        cache.set(cache_key, True, 60)

        if is_json_request(request): return JsonResponse({'status': 'success', 'message': 'Code resent'})
        messages.success(request, f"New code sent to {email_to}")
        
    except UserProfile.DoesNotExist:
        messages.error(request, "Profile not found.")
        
    return redirect('verify_email_change')

@login_required
@require_http_methods(["GET", "POST"])
def profile_settings(request):
    user = request.user

    if not user.is_authenticated:
        if is_json_request(request): 
            return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=401)
        return redirect('login')

    form = ProfileUpdateForm(instance=user)

    if request.method == 'POST':
        if 'request_email_change' in request.POST:
            cache_key = f"email_init_cooldown_{user.id}"
            if cache.get(cache_key):
                msg = "Please wait a minute before requesting another code."
                if is_json_request(request): return JsonResponse({'status': 'error', 'message': msg}, status=429)
                messages.warning(request, msg)
                return redirect('profile')
            try:
                dto = schemas.EmailChangeRequestDTO(
                    user_id=user.id, 
                    new_email=request.POST.get('email'),
                    current_email=user.email
                )

                raw_code = services.request_email_change(dto)

                send_async_email(
                    dto.new_email, 
                    "Email Change Verification", 
                    f"Your verification code is: {raw_code}"
                )

                cache.set(cache_key, True, 60)

                if is_json_request(request):
                    return JsonResponse({
                        'status': 'success', 
                        'message': 'Verification code sent.',
                        'next_step': 'Verify at /verify-email-change/'
                    })
                return redirect('verify_email_change')

            except Exception as e:
                if is_json_request(request):
                    return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
                messages.error(request, str(e))

        else:

            post_data = request.POST.copy()

            post_data['email'] = user.email

            form = ProfileUpdateForm(post_data, instance=user)
            
            if form.is_valid():
                try:
                    form.save()
                except Exception:
                    from django.db import IntegrityError
                    msg = "That username is already taken."
                    if is_json_request(request):
                        return JsonResponse({'status': 'error', 'message': msg}, status=400)
                    messages.error(request, msg)
                    return render(request, 'tracker/profile.html', {'form': form})

                if is_json_request(request): 
                    user_profile = user.userprofile
                    return JsonResponse({
                        'status': 'updated',
                        'data': {
                            'username': user.username,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'email': user.email, 
                            'currency': user_profile.currency_code
                        }
                    })
                
                messages.success(request, 'Profile updated.')
            else:
                if is_json_request(request):
                    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

    else:
        if is_json_request(request):
            user_profile = user.userprofile
            data = {
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'currency': user_profile.currency_code
            }
            return JsonResponse({'status': 'success', 'data': data})

    return render(request, 'tracker/profile_settings.html', {
        'form': form, 
        'profile': user.userprofile
    })



@require_GET
def password_change_done_custom(request):
    if is_json_request(request):
        return JsonResponse({
            'status': 'success', 
            'message': 'Password changed successfully.'
        })

    return render(request, 'tracker/password_change_done.html')

def custom_400_handler(request, exception=None):
    if is_json_request(request): return JsonResponse({'error': 'Bad Request'}, status=400)
    return render(request, 'errors/400.html', status=400)

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
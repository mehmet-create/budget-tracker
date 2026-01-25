from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # ==============================
    # 1. DASHBOARD & CORE
    # ==============================
    path('', views.dashboard, name='dashboard'),
    path('charts/', views.charts, name='charts'),
    path('api/location/update/', views.update_location_view, name='update_location'),

    # ==============================
    # 2. TRANSACTIONS
    # ==============================
    path('transactions/', views.transaction_list, name='transactions'),
    path('transactions/add/', views.add_transaction, name='add_transaction'),
    path('transaction/<int:pk>/edit/', views.edit_transaction, name='edit_transaction'),
    path('delete/<int:pk>/', views.delete_transaction, name='delete_transaction'),

    # ==============================
    # 3. BUDGET GOALS (All your custom logic is here)
    # ==============================
    path('goals/', views.goals_list, name='goals_list'),
    path('goals/<int:year>/<int:month>/', views.goals_list, name='goals_history'),
    path('set_goals/', views.set_goals, name='set_goals'),
    path('goals/edit/<int:pk>/', views.edit_goal, name='edit_goal'),
    path('goals/delete/<int:pk>/', views.delete_goal, name='delete_goal'),
    
    # *** Your Custom App Views are SAFE here: ***
    path('goals/clear/<int:year>/<int:month>/', views.clear_monthly_goals, name='clear_monthly_goals'),
    path('goals/import/', views.import_previous_goals, name='import_previous_goals'),

    # ==============================
    # 4. SETTINGS & PROFILE
    # ==============================
    path('profile/', views.profile_settings, name='profile'),
    path('settings/change_currency/', views.change_currency, name='change_currency'), # <-- Kept this
    path('profile/verify-email/', views.verify_email_change, name='verify_email_change'),
    path('profile/password/change/', views.password_change_view, name='password_change'),
    path('profile/password/change/done/', views.password_change_done_custom, name='password_change_done'),
    path('profile/delete/', views.delete_account_view, name='delete_account'),

    # ==============================
    # 5. AUTHENTICATION (Async)
    # ==============================
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('verify-registration/', views.verify_registration, name='verify_registration'),
    path('resend-code/', views.resend_code, name='resend_code'),
    path('cancel-registration/', views.cancel_registration, name='cancel_registration'),

    # ==============================
    # 6. PASSWORD RESET (Standard Django)
    # ==============================
    path('password-reset/', auth_views.PasswordResetView.as_view(template_name='tracker/password_reset.html'), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='tracker/password_reset_done.html'), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='tracker/password_reset_confirm.html'), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(template_name='tracker/password_reset_complete.html'), name='password_reset_complete'),
]

# Error Handlers
handler403 = 'tracker.views.custom_403_handler'
handler404 = 'tracker.views.custom_404_handler'
handler500 = 'tracker.views.custom_500_handler'
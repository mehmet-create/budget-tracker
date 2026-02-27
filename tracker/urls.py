from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [

    path('health/', views.health, name='health'),
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),#
    path('landing/', views.landing, name='landing'), 
    path('charts/', views.charts, name='charts'),#

    path('transactions/', views.transaction_list, name='transactions'),#
    path('transactions/add/', views.add_transaction, name='add_transaction'),#
    path('transaction/<int:pk>/edit/', views.edit_transaction, name='edit_transaction'),#
    path('transaction/delete/<int:pk>/', views.delete_transaction, name='delete_transaction'),#
    path('tools/audit/', views.subscription_audit_view, name='audit'),
    path('transactions/import/', views.import_transactions, name='import_csv'),

    path('goals/', views.goals_list, name='goals_list'),#
    path('goals/<int:year>/<int:month>/', views.goals_list, name='goals_history'),#
    path('set_goals/', views.set_goals, name='set_goals'),#
    path('goals/edit/<int:pk>/', views.edit_goal, name='edit_goal'),#
    path('goals/delete/<int:pk>/', views.delete_goal, name='delete_goal'),#
    path('goals/clear/<int:year>/<int:month>/', views.clear_monthly_goals, name='clear_monthly_goals'),#
    path('goals/import/', views.import_previous_goals, name='import_previous_goals'),#

    path('profile/', views.profile_settings, name='profile'),#
    path('settings/change_currency/', views.change_currency, name='change_currency'),#
    path('profile/verify-email/', views.verify_email_change, name='verify_email_change'),#
    path('profile/resend-code/', views.resend_verification_code_profile, name='resend_verification_code'),#
    path('profile/password/change/', views.password_change_view, name='password_change'),#
    path('profile/password/change/done/', views.password_change_done_custom, name='password_change_done'),#
    path('profile/delete/', views.delete_account_view, name='delete_account'),#

    path('login/', views.login_view, name='login'),#
    path('register/', views.register_view, name='register'),#
    path('logout/', views.logout_view, name='logout'),#
    path('verify-registration/', views.verify_registration, name='verify_registration'),#
    path('resend-code/', views.resend_code, name='resend_code'),#
    path('cancel-registration/', views.cancel_registration, name='cancel_registration'),#

    path('password-reset/', views.CustomPasswordResetView.as_view(template_name='tracker/password_reset.html'), name='password_reset'),#    
    path('password-reset/done/', views.CustomPasswordResetDoneView.as_view(template_name='tracker/password_reset_done.html'), name='password_reset_done'),#
    path('password-reset-confirm/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(template_name='tracker/password_reset_confirm.html'), name='password_reset_confirm'),
    path('password-reset-confirm-api/<uidb64>/<token>/', views.password_reset_confirm_api, name='password_reset_confirm_api'),
    path('password-reset-complete/', views.CustomPasswordResetCompleteView.as_view(template_name='tracker/password_reset_complete.html'), name='password_reset_complete'),
    ]

handler403 = 'tracker.views.custom_403_handler'
handler404 = 'tracker.views.custom_404_handler'
handler500 = 'tracker.views.custom_500_handler'
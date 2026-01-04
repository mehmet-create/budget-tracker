from django.urls import path
from . import views
from .views import CustomPasswordChangeView

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('transactions/', views.transaction_list, name='transactions'),
    path('settings/change_currency/', views.change_currency, name='change_currency'),
    path('transactions/add/', views.add_transaction, name='add_transaction'),
    path('charts/', views.charts, name='charts'),
    path("transaction/<int:pk>/edit/", views.edit_transaction, name='edit_transaction'),
    path('delete/<int:pk>/', views.delete_transaction, name='delete_transaction'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('goals/<int:year>/<int:month>/', views.goals_list, name='goals_history'),
    path('goals/', views.goals_list, name='goals_list'),
    path('goals/clear/<int:year>/<int:month>/', views.clear_monthly_goals, name='clear_monthly_goals'),
    path('goals/import/', views.import_previous_goals, name='import_previous_goals'),   
    path('set_goals/', views.set_goals, name='set_goals'),
    path('goals/edit/<int:pk>/', views.edit_goal, name='edit_goal'),
    path('goals/delete/<int:pk>/', views.delete_goal, name='delete_goal'),
    path('profile/', views.profile_settings, name='profile'),
    path(
        'profile/password/change/', CustomPasswordChangeView.as_view(), name='password_change'
    ),
    path('profile/password/change/done/', views.password_change_done_custom, name='password_change_done'),
]

handler403 = 'tracker.views.custom_403_handler'
handler404 = 'tracker.views.custom_404_handler'
handler500 = 'tracker.views.custom_500_handler'
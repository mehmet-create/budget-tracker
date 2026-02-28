"""
URL configuration for budget project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Error handlers must live in the ROOT URLconf (this file), not in app urls.py
handler400 = 'tracker.views.custom_400_handler'
handler403 = 'tracker.views.custom_403_handler'
handler404 = 'tracker.views.custom_404_handler'
handler500 = 'tracker.views.custom_500_handler'

urlpatterns = [
    path('secure-admin-9f3k76/', admin.site.urls),
    path('', include('tracker.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
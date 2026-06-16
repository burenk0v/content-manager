"""mysite URL Configuration"""

from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', include('auth_app.urls')),
    path('', lambda request: redirect('auth_app:login')),
]
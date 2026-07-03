from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import requests
import os

def login_view(request):
    """Страница входа"""
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('auth_app:dashboard')
        else:
            messages.error(request, 'Неверное имя пользователя или пароль')
    
    return render(request, 'auth_app/login.html')

@login_required
def dashboard_view(request):
    """Защищенная страница после входа"""
    backend_status = "Неизвестно"
    backend_url = os.environ.get('BACKEND_API_URL', 'http://localhost:8000/api')
    
    try:
        response = requests.get(backend_url, timeout=5)
        if response.status_code == 200 and response.json()["status"] == 'Backend running':
            backend_status = "Работает"
        else:
            backend_status = "Не работает"
    except Exception:
        backend_status = "Не работает"
    
    return render(request, 'auth_app/dashboard.html', {'backend_status': backend_status})

def logout_view(request):
    """Выход из системы"""
    logout(request)
    return redirect('auth_app:login')

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
import requests
import os


def login_view(request):
    """Login page"""
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('auth_app:dashboard')
        else:
            messages.error(request, 'Invalid username or password')
    
    return render(request, 'auth_app/login.html')

@login_required
def dashboard_view(request):
    """Protected page after login"""
    backend_status = "Unknown"
    backend_url = os.environ.get('BACKEND_API_URL', 'http://localhost:8000/api')
    
    try:
        headers = {}
        service_token = os.environ.get('SERVICE_ACCOUNT_TOKEN')
        if service_token:
            headers['X-Service-Token'] = service_token

        response = requests.get(backend_url, headers=headers, timeout=5)
        if response.status_code == 200 and response.json()["status"] == 'Backend running':
            backend_status = "Running"
        else:
            backend_status = "Not working"
    except Exception:
        backend_status = "Not working"
    
    return render(request, 'auth_app/dashboard.html', {'backend_status': backend_status})

def logout_view(request):
    """Выход из системы"""
    logout(request)
    return redirect('auth_app:login')

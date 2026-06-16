from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required

def login_view(request):
    """Страница входа"""
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Неверное имя пользователя или пароль')
    
    return render(request, 'auth_app/login.html')

@login_required
def dashboard_view(request):
    """Защищенная страница после входа"""
    return render(request, 'auth_app/dashboard.html')

def logout_view(request):
    """Выход из системы"""
    logout(request)
    return redirect('login')
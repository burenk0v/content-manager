from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
import requests
import os

BACKEND_API_URL = os.environ.get('BACKEND_API_URL', 'http://localhost:8000')
SERVICE_TOKEN = os.environ.get('SERVICE_ACCOUNT_TOKEN')


def backend_request(method: str, path: str, json=None, timeout=10):
    url = f"{BACKEND_API_URL.rstrip('/')}{path}"
    headers = {}
    if SERVICE_TOKEN:
        headers['X-Service-Token'] = SERVICE_TOKEN
    return requests.request(method, url, json=json, headers=headers, timeout=timeout)


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
    """Protected dashboard page with counts only."""
    backend_status = "Unknown"
    topic_count = 0
    schedule_count = 0

    try:
        response = requests.get(f"{BACKEND_API_URL.rstrip('/')}/", timeout=5)
        if response.status_code == 200 and response.json().get('status') == 'Backend running':
            backend_status = 'Running'
        else:
            backend_status = 'Not working'
    except Exception:
        backend_status = 'Not working'

    try:
        topics_response = backend_request('get', '/content/topics')
        if topics_response.status_code == 200:
            topic_count = len(topics_response.json())
        schedules_response = backend_request('get', '/content/schedules')
        if schedules_response.status_code == 200:
            schedule_count = len(schedules_response.json())
    except Exception:
        messages.error(request, 'Unable to load backend counts.')

    return render(request, 'auth_app/dashboard.html', {
        'backend_status': backend_status,
        'topic_count': topic_count,
        'schedule_count': schedule_count,
    })


@login_required
def topics_view(request):
    backend_status = 'Unknown'
    topics = []

    try:
        response = requests.get(f"{BACKEND_API_URL.rstrip('/')}/", timeout=5)
        if response.status_code == 200 and response.json().get('status') == 'Backend running':
            backend_status = 'Running'
        else:
            backend_status = 'Not working'
    except Exception:
        backend_status = 'Not working'

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'create_topic':
                payload = {
                    'name': request.POST.get('topic_name', '').strip(),
                    'language': request.POST.get('topic_language', '').strip(),
                }
                result = backend_request('post', '/content/topics', json=payload)
                if result.status_code == 201:
                    messages.success(request, 'Topic added successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to add topic'))
                return redirect('auth_app:topics')

            if action == 'delete_topic':
                topic_id = request.POST.get('topic_id')
                result = backend_request('delete', f'/content/topics/{topic_id}')
                if result.status_code in (200, 204):
                    messages.success(request, 'Topic deleted successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to delete topic'))
                return redirect('auth_app:topics')
        except requests.RequestException as exc:
            messages.error(request, f'Backend request failed: {exc}')
            return redirect('auth_app:topics')

    try:
        topics_response = backend_request('get', '/content/topics')
        if topics_response.status_code == 200:
            topics = topics_response.json()
    except Exception:
        messages.error(request, 'Unable to load topics.')

    return render(request, 'auth_app/topics.html', {
        'backend_status': backend_status,
        'topics': topics,
    })


@login_required
def schedules_view(request):
    backend_status = 'Unknown'
    schedules = []
    edit_schedule = None

    try:
        response = requests.get(f"{BACKEND_API_URL.rstrip('/')}/", timeout=5)
        if response.status_code == 200 and response.json().get('status') == 'Backend running':
            backend_status = 'Running'
        else:
            backend_status = 'Not working'
    except Exception:
        backend_status = 'Not working'

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'create_schedule':
                payload = {
                    'name': request.POST.get('schedule_name', '').strip(),
                    'chat_id': request.POST.get('chat_id', '').strip(),
                    'chat_name': request.POST.get('chat_name', '').strip(),
                    'language': request.POST.get('schedule_language', '').strip(),
                    'assistant_message': request.POST.get('assistant_message', '').strip(),
                    'schedule_type': request.POST.get('schedule_type', '').strip(),
                    'schedule_value': request.POST.get('schedule_value', '').strip(),
                    'is_active': request.POST.get('is_active') == 'on',
                }
                result = backend_request('post', '/content/schedules', json=payload)
                if result.status_code == 201:
                    messages.success(request, 'Schedule created successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to create schedule'))
                return redirect('auth_app:schedules')

            if action == 'update_schedule':
                schedule_id = request.POST.get('schedule_id')
                payload = {
                    'name': request.POST.get('schedule_name', '').strip(),
                    'chat_id': request.POST.get('chat_id', '').strip(),
                    'chat_name': request.POST.get('chat_name', '').strip(),
                    'language': request.POST.get('schedule_language', '').strip(),
                    'assistant_message': request.POST.get('assistant_message', '').strip(),
                    'schedule_type': request.POST.get('schedule_type', '').strip(),
                    'schedule_value': request.POST.get('schedule_value', '').strip(),
                    'is_active': request.POST.get('is_active') == 'on',
                }
                result = backend_request('put', f'/content/schedules/{schedule_id}', json=payload)
                if result.status_code == 200:
                    messages.success(request, 'Schedule updated successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to update schedule'))
                return redirect('auth_app:schedules')

            if action == 'delete_schedule':
                schedule_id = request.POST.get('schedule_id')
                result = backend_request('delete', f'/content/schedules/{schedule_id}')
                if result.status_code in (200, 204):
                    messages.success(request, 'Schedule deleted successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to delete schedule'))
                return redirect('auth_app:schedules')
        except requests.RequestException as exc:
            messages.error(request, f'Backend request failed: {exc}')
            return redirect('auth_app:schedules')

    try:
        schedules_response = backend_request('get', '/content/schedules')
        if schedules_response.status_code == 200:
            schedules = schedules_response.json()
    except Exception:
        messages.error(request, 'Unable to load schedules.')

    edit_schedule_id = request.GET.get('edit_schedule')
    if edit_schedule_id:
        edit_schedule = next((item for item in schedules if str(item.get('id')) == edit_schedule_id), None)

    return render(request, 'auth_app/schedules.html', {
        'backend_status': backend_status,
        'schedules': schedules,
        'edit_schedule': edit_schedule,
    })


def logout_view(request):
    """Выход из системы"""
    logout(request)
    return redirect('auth_app:login')

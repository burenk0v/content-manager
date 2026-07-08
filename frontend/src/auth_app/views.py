from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.urls import reverse
import requests
import os

from auth_app.models import set_user_theme
from auth_app.timezone_utils import (
    compute_schedule_next_run_display,
    convert_local_time_to_utc,
    convert_utc_time_to_local,
)

BACKEND_API_URL = os.environ.get('BACKEND_API_URL', 'http://localhost:8000')
SERVICE_TOKEN = os.environ.get('SERVICE_ACCOUNT_TOKEN')
LANGUAGE_OPTIONS = [
    ('ru', 'Russian'),
    ('en', 'English'),
    ('es', 'Spanish'),
]
TIMEZONE_OPTIONS = [
    ('UTC', 'UTC'),
    ('Europe/London', 'Europe/London'),
    ('Europe/Berlin', 'Europe/Berlin'),
    ('Europe/Moscow', 'Europe/Moscow'),
    ('Asia/Tokyo', 'Asia/Tokyo'),
    ('America/New_York', 'America/New_York'),
    ('America/Los_Angeles', 'America/Los_Angeles'),
]


def backend_request(method: str, path: str, json=None, timeout=10):
    url = f"{BACKEND_API_URL.rstrip('/')}{path}"
    headers = {}
    if SERVICE_TOKEN:
        headers['X-Service-Token'] = SERVICE_TOKEN
    return requests.request(method, url, json=json, headers=headers, timeout=timeout)


def get_backend_health():
    status = { 'backend': 'Unknown', 'db': 'Unknown' }
    try:
        response = requests.get(f"{BACKEND_API_URL.rstrip('/')}/", timeout=5)
        if response.status_code == 200 and response.json().get('status') == 'Backend running':
            status['backend'] = 'Running'
        else:
            status['backend'] = 'Not working'
    except Exception:
        status['backend'] = 'Not working'

    try:
        response = requests.get(f"{BACKEND_API_URL.rstrip('/')}/health/db", timeout=5)
        if response.status_code == 200 and response.json().get('status') == 'ok':
            status['db'] = 'Running'
        else:
            status['db'] = 'Not working'
    except Exception:
        status['db'] = 'Not working'

    return status


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
def set_theme_view(request):
    if request.method == 'POST':
        theme = request.POST.get('theme', '')
        set_user_theme(request.user, theme)
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'auth_app:dashboard'
    return redirect(next_url)


@login_required
def dashboard_view(request):
    """Protected dashboard page with counts only."""
    health = get_backend_health()
    backend_status = health['backend']
    db_status = health['db']
    topic_count = 0
    schedule_count = 0
    prompt_count = 0
    assistant_message_count = 0
    draft_count = 0

    try:
        topics_response = backend_request('get', '/content/topics')
        if topics_response.status_code == 200:
            topic_count = len(topics_response.json())
        prompts_response = backend_request('get', '/content/prompts')
        if prompts_response.status_code == 200:
            prompt_count = len(prompts_response.json())
        assistant_messages_response = backend_request('get', '/content/assistant-messages')
        if assistant_messages_response.status_code == 200:
            assistant_message_count = len(assistant_messages_response.json())
        schedules_response = backend_request('get', '/content/schedules')
        if schedules_response.status_code == 200:
            schedule_count = len(schedules_response.json())
        drafts_response = backend_request('get', '/content/drafts')
        if drafts_response.status_code == 200:
            draft_count = len(drafts_response.json())
    except Exception:
        messages.error(request, 'Unable to load backend counts.')

    return render(request, 'auth_app/dashboard.html', {
        'backend_status': backend_status,
        'db_status': db_status,
        'topic_count': topic_count,
        'prompt_count': prompt_count,
        'assistant_message_count': assistant_message_count,
        'schedule_count': schedule_count,
        'draft_count': draft_count,
    })


@login_required
def topics_view(request):
    topics = []

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'delete_topic':
                topic_id = request.POST.get('topic_id')
                result = backend_request('delete', f'/content/topics/{topic_id}')
                if result.status_code in (200, 204):
                    messages.success(request, 'Topic deleted successfully.')
                else:
                    error_detail = 'Unable to delete topic'
                    if result.text:
                        try:
                            error_detail = result.json().get('detail', error_detail)
                        except ValueError:
                            error_detail = result.text
                    messages.error(request, error_detail)
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
        'topics': topics,
    })


@login_required
def prompts_view(request):
    prompts = []
    edit_prompt = None

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'start_edit_prompt':
                prompt_id = request.POST.get('prompt_id', '').strip()
                if prompt_id.isdigit():
                    return redirect(f"{reverse('auth_app:prompts')}?edit={prompt_id}")
                messages.error(request, 'Invalid prompt id')
                return redirect('auth_app:prompts')

            if action == 'create_prompt':
                payload = {
                    'name': request.POST.get('prompt_name', '').strip(),
                    'language': request.POST.get('prompt_language', '').strip(),
                    'text': request.POST.get('prompt_text', ''),
                }
                result = backend_request('post', '/content/prompts', json=payload)
                if result.status_code == 201:
                    messages.success(request, 'Prompt created successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to create prompt'))
                return redirect('auth_app:prompts')

            if action == 'update_prompt':
                prompt_id = request.POST.get('prompt_id', '').strip()
                if not prompt_id.isdigit():
                    messages.error(request, 'Invalid prompt id')
                    return redirect('auth_app:prompts')
                payload = {
                    'name': request.POST.get('prompt_name', '').strip(),
                    'language': request.POST.get('prompt_language', '').strip(),
                    'text': request.POST.get('prompt_text', ''),
                }
                result = backend_request('put', f'/content/prompts/{prompt_id}', json=payload)
                if result.status_code == 200:
                    messages.success(request, 'Prompt updated successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to update prompt'))
                return redirect('auth_app:prompts')

            if action == 'delete_prompt':
                prompt_id = request.POST.get('prompt_id')
                result = backend_request('delete', f'/content/prompts/{prompt_id}')
                if result.status_code in (200, 204):
                    messages.success(request, 'Prompt deleted successfully.')
                else:
                    error_detail = 'Unable to delete prompt'
                    if result.text:
                        try:
                            error_detail = result.json().get('detail', error_detail)
                        except ValueError:
                            error_detail = result.text
                    messages.error(request, error_detail)
                return redirect('auth_app:prompts')
        except requests.RequestException as exc:
            messages.error(request, f'Backend request failed: {exc}')
            return redirect('auth_app:prompts')

    try:
        prompts_response = backend_request('get', '/content/prompts')
        if prompts_response.status_code == 200:
            prompts = prompts_response.json()
            edit_id = request.GET.get('edit', '').strip()
            if edit_id.isdigit():
                edit_prompt = next((prompt for prompt in prompts if prompt.get('id') == int(edit_id)), None)
                if edit_prompt is None:
                    messages.error(request, 'Prompt for editing not found.')
    except Exception:
        messages.error(request, 'Unable to load prompts.')

    return render(request, 'auth_app/prompts.html', {
        'prompts': prompts,
        'edit_prompt': edit_prompt,
    })


@login_required
def assistant_messages_view(request):
    assistant_messages = []
    edit_assistant_message = None

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'start_edit_assistant_message':
                assistant_message_id = request.POST.get('assistant_message_id', '').strip()
                if assistant_message_id.isdigit():
                    return redirect(f"{reverse('auth_app:assistant_messages')}?edit={assistant_message_id}")
                messages.error(request, 'Invalid assistant message id')
                return redirect('auth_app:assistant_messages')

            if action == 'create_assistant_message':
                payload = {
                    'name': request.POST.get('assistant_message_name', '').strip(),
                    'language': request.POST.get('assistant_message_language', '').strip(),
                    'text': request.POST.get('assistant_message_text', ''),
                }
                result = backend_request('post', '/content/assistant-messages', json=payload)
                if result.status_code == 201:
                    messages.success(request, 'Assistant message created successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to create assistant message'))
                return redirect('auth_app:assistant_messages')

            if action == 'update_assistant_message':
                assistant_message_id = request.POST.get('assistant_message_id', '').strip()
                if not assistant_message_id.isdigit():
                    messages.error(request, 'Invalid assistant message id')
                    return redirect('auth_app:assistant_messages')
                payload = {
                    'name': request.POST.get('assistant_message_name', '').strip(),
                    'language': request.POST.get('assistant_message_language', '').strip(),
                    'text': request.POST.get('assistant_message_text', ''),
                }
                result = backend_request('put', f'/content/assistant-messages/{assistant_message_id}', json=payload)
                if result.status_code == 200:
                    messages.success(request, 'Assistant message updated successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to update assistant message'))
                return redirect('auth_app:assistant_messages')

            if action == 'delete_assistant_message':
                assistant_message_id = request.POST.get('assistant_message_id')
                result = backend_request('delete', f'/content/assistant-messages/{assistant_message_id}')
                if result.status_code in (200, 204):
                    messages.success(request, 'Assistant message deleted successfully.')
                else:
                    error_detail = 'Unable to delete assistant message'
                    if result.text:
                        try:
                            error_detail = result.json().get('detail', error_detail)
                        except ValueError:
                            error_detail = result.text
                    messages.error(request, error_detail)
                return redirect('auth_app:assistant_messages')
        except requests.RequestException as exc:
            messages.error(request, f'Backend request failed: {exc}')
            return redirect('auth_app:assistant_messages')

    try:
        assistant_messages_response = backend_request('get', '/content/assistant-messages')
        if assistant_messages_response.status_code == 200:
            assistant_messages = assistant_messages_response.json()
            edit_id = request.GET.get('edit', '').strip()
            if edit_id.isdigit():
                edit_assistant_message = next(
                    (item for item in assistant_messages if item.get('id') == int(edit_id)),
                    None,
                )
                if edit_assistant_message is None:
                    messages.error(request, 'Assistant message for editing not found.')
    except Exception:
        messages.error(request, 'Unable to load assistant messages.')

    return render(request, 'auth_app/assistant_messages.html', {
        'assistant_messages': assistant_messages,
        'edit_assistant_message': edit_assistant_message,
    })


@login_required
def schedules_view(request):
    schedules = []
    edit_schedule = None
    valid_timezones = {value for value, _ in TIMEZONE_OPTIONS}
    schedule_timezone = request.GET.get('schedule_timezone', 'UTC')
    if schedule_timezone not in valid_timezones:
        schedule_timezone = 'UTC'

    if request.method == 'POST':
        action = request.POST.get('action')
        schedule_timezone = request.POST.get('schedule_timezone', 'UTC')
        if schedule_timezone not in valid_timezones:
            schedule_timezone = 'UTC'
        try:
            if action == 'create_schedule':
                schedule_type = request.POST.get('schedule_type', '').strip()
                schedule_value = request.POST.get('schedule_value', '').strip()
                prompt_id_raw = request.POST.get('prompt_id')
                prompt_id = int(prompt_id_raw) if prompt_id_raw and prompt_id_raw.strip().isdigit() else None
                assistant_template_id_raw = request.POST.get('assistant_template_id')
                assistant_template_id = int(assistant_template_id_raw) if assistant_template_id_raw and assistant_template_id_raw.strip().isdigit() else None
                if schedule_type == 'daily':
                    schedule_value = convert_local_time_to_utc(schedule_value, schedule_timezone)
                payload = {
                    'name': request.POST.get('schedule_name', '').strip(),
                    'chat_id': request.POST.get('chat_id', '').strip(),
                    'chat_name': request.POST.get('chat_name', '').strip(),
                    'language': request.POST.get('schedule_language', '').strip(),
                    'assistant_message': request.POST.get('assistant_message', ''),
                    'prompt_id': prompt_id,
                    'assistant_template_id': assistant_template_id,
                    'timezone': schedule_timezone,
                    'schedule_type': schedule_type,
                    'schedule_value': schedule_value,
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
                schedule_type = request.POST.get('schedule_type', '').strip()
                schedule_value = request.POST.get('schedule_value', '').strip()
                prompt_id_raw = request.POST.get('prompt_id')
                prompt_id = int(prompt_id_raw) if prompt_id_raw and prompt_id_raw.strip().isdigit() else None
                assistant_template_id_raw = request.POST.get('assistant_template_id')
                assistant_template_id = int(assistant_template_id_raw) if assistant_template_id_raw and assistant_template_id_raw.strip().isdigit() else None
                if schedule_type == 'daily':
                    schedule_value = convert_local_time_to_utc(schedule_value, schedule_timezone)
                payload = {
                    'name': request.POST.get('schedule_name', '').strip(),
                    'chat_id': request.POST.get('chat_id', '').strip(),
                    'chat_name': request.POST.get('chat_name', '').strip(),
                    'language': request.POST.get('schedule_language', '').strip(),
                    'assistant_message': request.POST.get('assistant_message', ''),
                    'prompt_id': prompt_id,
                    'assistant_template_id': assistant_template_id,
                    'timezone': schedule_timezone,
                    'schedule_type': schedule_type,
                    'schedule_value': schedule_value,
                    'is_active': request.POST.get('is_active') == 'on',
                }
                result = backend_request('put', f'/content/schedules/{schedule_id}', json=payload)
                if result.status_code == 200:
                    messages.success(request, 'Schedule updated successfully.')
                else:
                    messages.error(request, result.json().get('detail', 'Unable to update schedule'))
                return redirect('auth_app:schedules')

            if action == 'toggle_schedule_active':
                schedule_id = request.POST.get('schedule_id')
                is_active = request.POST.get('is_active') == 'on'
                payload = {'is_active': is_active}
                result = backend_request('put', f'/content/schedules/{schedule_id}', json=payload)
                if result.status_code == 200:
                    messages.success(request, f"Schedule {'enabled' if is_active else 'disabled'}.")
                else:
                    messages.error(request, result.json().get('detail', 'Unable to update schedule status'))
                return redirect('auth_app:schedules')

            if action == 'delete_schedule':
                schedule_id = request.POST.get('schedule_id')
                result = backend_request('delete', f'/content/schedules/{schedule_id}')
                if result.status_code in (200, 204):
                    messages.success(request, 'Schedule deleted successfully.')
                else:
                    error_detail = 'Unable to delete schedule'
                    if result.text:
                        try:
                            error_detail = result.json().get('detail', error_detail)
                        except ValueError:
                            error_detail = result.text
                    messages.error(request, error_detail)
                return redirect('auth_app:schedules')
        except requests.RequestException as exc:
            messages.error(request, f'Backend request failed: {exc}')
            return redirect('auth_app:schedules')

    try:
        schedules_response = backend_request('get', '/content/schedules')
        if schedules_response.status_code == 200:
            schedules = schedules_response.json()
            for schedule in schedules:
                item_timezone = schedule.get('timezone') or 'UTC'
                schedule['timezone'] = item_timezone
                schedule['next_run'] = compute_schedule_next_run_display(schedule, item_timezone)
    except Exception:
        messages.error(request, 'Unable to load schedules.')

    prompts = []
    try:
        prompts_response = backend_request('get', '/content/prompts')
        if prompts_response.status_code == 200:
            prompts = prompts_response.json()
    except Exception:
        messages.error(request, 'Unable to load prompts.')

    assistant_messages = []
    try:
        assistant_messages_response = backend_request('get', '/content/assistant-messages')
        if assistant_messages_response.status_code == 200:
            assistant_messages = assistant_messages_response.json()
    except Exception:
        messages.error(request, 'Unable to load assistant messages.')

    edit_schedule_id = request.GET.get('edit_schedule')
    if edit_schedule_id:
        edit_schedule = next((item for item in schedules if str(item.get('id')) == edit_schedule_id), None)
        if edit_schedule:
            schedule_timezone = edit_schedule.get('timezone') or 'UTC'
        if edit_schedule and edit_schedule.get('schedule_type') == 'daily':
            edit_schedule = dict(edit_schedule)
            edit_schedule['schedule_value'] = convert_utc_time_to_local(
                edit_schedule.get('schedule_value', ''),
                schedule_timezone,
            )

    return render(request, 'auth_app/schedules.html', {
        'language_options': LANGUAGE_OPTIONS,
        'timezones': TIMEZONE_OPTIONS,
        'schedule_timezone': schedule_timezone,
        'schedules': schedules,
        'prompts': prompts,
        'assistant_messages': assistant_messages,
        'edit_schedule': edit_schedule,
    })


@login_required
def drafts_view(request):
    drafts = []

    if request.method == 'POST':
        action = request.POST.get('action')
        draft_id = request.POST.get('draft_id')
        try:
            if action == 'delete_draft':
                result = backend_request('delete', f'/content/drafts/{draft_id}')
                if result.status_code in (200, 204):
                    messages.success(request, 'Draft deleted successfully.')
                else:
                    error_detail = 'Unable to delete draft'
                    if result.text:
                        try:
                            error_detail = result.json().get('detail', error_detail)
                        except ValueError:
                            error_detail = result.text
                    messages.error(request, error_detail)
                return redirect('auth_app:drafts')

            if action == 'publish_draft':
                result = backend_request('patch', f'/content/drafts/{draft_id}', json={'status': 'published'})
                if result.status_code == 200:
                    messages.success(request, 'Draft approved and published.')
                else:
                    error_detail = 'Unable to publish draft'
                    if result.text:
                        try:
                            error_detail = result.json().get('detail', error_detail)
                        except ValueError:
                            error_detail = result.text
                    messages.error(request, error_detail)
                return redirect('auth_app:drafts')

            if action == 'reject_draft':
                result = backend_request('patch', f'/content/drafts/{draft_id}', json={'status': 'rejected'})
                if result.status_code == 200:
                    messages.success(request, 'Draft rejected successfully.')
                else:
                    error_detail = 'Unable to reject draft'
                    if result.text:
                        try:
                            error_detail = result.json().get('detail', error_detail)
                        except ValueError:
                            error_detail = result.text
                    messages.error(request, error_detail)
                return redirect('auth_app:drafts')
        except requests.RequestException as exc:
            messages.error(request, f'Backend request failed: {exc}')
            return redirect('auth_app:drafts')

    try:
        drafts_response = backend_request('get', '/content/drafts')
        if drafts_response.status_code == 200:
            drafts = drafts_response.json()
    except Exception:
        messages.error(request, 'Unable to load drafts.')

    return render(request, 'auth_app/drafts.html', {
        'drafts': drafts,
    })


def logout_view(request):
    """Выход из системы"""
    logout(request)
    return redirect('auth_app:login')

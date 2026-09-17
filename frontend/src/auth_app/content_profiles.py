import os

import requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

BACKEND_API_URL = os.environ.get('BACKEND_API_URL', 'http://localhost:8000')
SERVICE_TOKEN = os.environ.get('SERVICE_ACCOUNT_TOKEN')

LANGUAGE_OPTIONS = [('ru', 'Russian'), ('en', 'English'), ('es', 'Spanish')]
TIMEZONE_OPTIONS = [
    ('UTC', 'UTC'),
    ('Europe/London', 'Europe/London'),
    ('Europe/Berlin', 'Europe/Berlin'),
    ('Europe/Moscow', 'Europe/Moscow'),
    ('Asia/Tokyo', 'Asia/Tokyo'),
    ('America/New_York', 'America/New_York'),
    ('America/Los_Angeles', 'America/Los_Angeles'),
]


def backend_request(method, path, json=None, params=None, timeout=10):
    headers = {'X-Service-Token': SERVICE_TOKEN} if SERVICE_TOKEN else {}
    return requests.request(
        method,
        f'{BACKEND_API_URL.rstrip("/")}{path}',
        json=json,
        params=params,
        headers=headers,
        timeout=timeout,
    )


def _detail(response, fallback):
    try:
        return response.json().get('detail', fallback)
    except ValueError:
        return fallback


@login_required
def content_profiles_view(request):
    profiles = []
    workspaces = []
    channels = []
    edit_profile = None

    try:
        workspace_response = backend_request('get', '/content/workspaces')
        if workspace_response.status_code == 200:
            workspaces = workspace_response.json()

        workspace_id = request.POST.get('workspace_id') or request.GET.get('workspace_id')
        if workspace_id:
            channel_response = backend_request(
                'get', '/content/channels', params={'workspace_id': workspace_id}
            )
            if channel_response.status_code == 200:
                channels = channel_response.json()

        profiles_response = backend_request('get', '/content/profiles')
        if profiles_response.status_code == 200:
            profiles = profiles_response.json()
            edit_id = request.GET.get('edit', '').strip()
            if edit_id.isdigit():
                edit_profile = next(
                    (item for item in profiles if item.get('id') == int(edit_id)), None
                )
    except requests.RequestException as exc:
        messages.error(request, f'Backend request failed: {exc}')

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'delete':
                profile_id = request.POST.get('profile_id', '').strip()
                response = backend_request('delete', f'/content/profiles/{profile_id}')
                if response.status_code == 204:
                    messages.success(request, 'Content profile deleted.')
                else:
                    messages.error(request, _detail(response, 'Unable to delete profile.'))
                return redirect('auth_app:content_profiles')

            if action == 'regenerate':
                profile_id = request.POST.get('profile_id', '').strip()
                response = backend_request('post', f'/content/profiles/{profile_id}/regenerate')
                if response.status_code == 200:
                    messages.success(request, 'Regeneration requested. Telegram will handle the next run.')
                else:
                    messages.error(request, _detail(response, 'Unable to request regeneration.'))
                return redirect('auth_app:content_profiles')

            if action in ('create', 'update'):
                payload = {
                    'workspace_id': int(request.POST.get('workspace_id')),
                    'channel_id': int(request.POST.get('channel_id')),
                    'name': request.POST.get('name', '').strip(),
                    'language': request.POST.get('language', 'en').strip(),
                    'topic_niche': request.POST.get('topic_niche', '').strip() or None,
                    'tone': request.POST.get('tone', '').strip() or None,
                    'content_format': request.POST.get('content_format', '').strip() or None,
                    'rules': request.POST.get('rules', '').strip() or None,
                    'timezone': request.POST.get('timezone', 'UTC').strip(),
                    'schedule_type': request.POST.get('schedule_type', 'daily'),
                    'schedule_value': request.POST.get('schedule_value', '').strip(),
                    'is_active': request.POST.get('is_active') == 'on',
                }
                profile_id = request.POST.get('profile_id', '').strip()
                path = f'/content/profiles/{profile_id}' if action == 'update' else '/content/profiles'
                response = backend_request('put' if action == 'update' else 'post', path, json=payload)
                if response.status_code in (200, 201):
                    messages.success(request, 'Content profile saved.')
                else:
                    messages.error(request, _detail(response, 'Unable to save content profile.'))
                return redirect('auth_app:content_profiles')
        except (ValueError, requests.RequestException) as exc:
            messages.error(request, f'Unable to save content profile: {exc}')
            return redirect('auth_app:content_profiles')

    return render(request, 'auth_app/content_profiles.html', {
        'profiles': profiles,
        'workspaces': workspaces,
        'channels': channels,
        'edit_profile': edit_profile,
        'language_options': LANGUAGE_OPTIONS,
        'timezone_options': TIMEZONE_OPTIONS,
    })

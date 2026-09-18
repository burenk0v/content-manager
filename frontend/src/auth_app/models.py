from django.contrib.auth.models import User
from django.db import models

THEME_CHOICES = [
    ("light", "Light"),
    ("dark", "Dark"),
]
DEFAULT_THEME = "light"


class UserPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preference")
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default=DEFAULT_THEME)


class UserTelegramSettings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="telegram_settings")
    bot_token = models.TextField(blank=True, default="")
    openai_api_key = models.TextField(blank=True, default="")
    admins = models.CharField(max_length=500, blank=True, default="")
    webapp_url = models.CharField(max_length=500, blank=True, default="")
    service_account_token = models.TextField(blank=True, default="")
    backend_api_url = models.CharField(max_length=500, blank=True, default="")
    schedule_check_interval_seconds = models.PositiveIntegerField(default=10)


def get_user_theme(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return DEFAULT_THEME
    preference, _ = UserPreference.objects.get_or_create(user=user, defaults={"theme": DEFAULT_THEME})
    return preference.theme


def set_user_theme(user, theme: str) -> str:
    normalized_theme = theme if theme in dict(THEME_CHOICES) else DEFAULT_THEME
    if not getattr(user, "is_authenticated", False):
        return DEFAULT_THEME
    preference, _ = UserPreference.objects.get_or_create(user=user, defaults={"theme": normalized_theme})
    if preference.theme != normalized_theme:
        preference.theme = normalized_theme
        preference.save(update_fields=["theme"])
    return preference.theme


def get_user_telegram_settings(user, defaults: dict):
    if not getattr(user, "is_authenticated", False):
        return defaults.copy()
    settings_obj, _ = UserTelegramSettings.objects.get_or_create(user=user, defaults=defaults)
    return {
        "bot_token": settings_obj.bot_token,
        "openai_api_key": settings_obj.openai_api_key,
        "admins": settings_obj.admins,
        "webapp_url": settings_obj.webapp_url,
        "service_account_token": settings_obj.service_account_token,
        "backend_api_url": settings_obj.backend_api_url,
        "schedule_check_interval_seconds": settings_obj.schedule_check_interval_seconds,
    }


def set_user_telegram_settings(user, values: dict, defaults: dict):
    if not getattr(user, "is_authenticated", False):
        return defaults.copy()
    settings_obj, _ = UserTelegramSettings.objects.get_or_create(user=user, defaults=defaults)
    settings_obj.bot_token = values.get("bot_token", "")
    settings_obj.openai_api_key = values.get("openai_api_key", "")
    settings_obj.admins = values.get("admins", "")
    settings_obj.webapp_url = values.get("webapp_url", "")
    settings_obj.service_account_token = values.get("service_account_token", "")
    settings_obj.backend_api_url = values.get("backend_api_url", "")
    settings_obj.schedule_check_interval_seconds = values.get("schedule_check_interval_seconds", 10)
    settings_obj.save()
    return {
        "bot_token": settings_obj.bot_token,
        "openai_api_key": settings_obj.openai_api_key,
        "admins": settings_obj.admins,
        "webapp_url": settings_obj.webapp_url,
        "service_account_token": settings_obj.service_account_token,
        "backend_api_url": settings_obj.backend_api_url,
        "schedule_check_interval_seconds": settings_obj.schedule_check_interval_seconds,
    }

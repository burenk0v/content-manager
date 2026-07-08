from django.contrib.auth.models import User
from django.db import connection, models


THEME_CHOICES = [
	('light', 'Light'),
	('dark', 'Dark'),
]
DEFAULT_THEME = 'light'


class UserPreference(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preference')
	theme = models.CharField(max_length=10, choices=THEME_CHOICES, default=DEFAULT_THEME)


def ensure_preferences_schema():
	existing_tables = set(connection.introspection.table_names())
	if UserPreference._meta.db_table in existing_tables:
		return
	with connection.schema_editor() as schema_editor:
		schema_editor.create_model(UserPreference)


def get_user_theme(user) -> str:
	if not getattr(user, 'is_authenticated', False):
		return DEFAULT_THEME
	ensure_preferences_schema()
	preference, _ = UserPreference.objects.get_or_create(user=user, defaults={'theme': DEFAULT_THEME})
	return preference.theme


def set_user_theme(user, theme: str) -> str:
	normalized_theme = theme if theme in dict(THEME_CHOICES) else DEFAULT_THEME
	if not getattr(user, 'is_authenticated', False):
		return DEFAULT_THEME
	ensure_preferences_schema()
	preference, _ = UserPreference.objects.get_or_create(user=user, defaults={'theme': normalized_theme})
	if preference.theme != normalized_theme:
		preference.theme = normalized_theme
		preference.save(update_fields=['theme'])
	return preference.theme
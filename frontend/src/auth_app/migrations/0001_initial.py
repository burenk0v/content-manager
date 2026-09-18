from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [
        migrations.CreateModel(
            name="UserPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("theme", models.CharField(choices=[("light", "Light"), ("dark", "Dark")], default="light", max_length=10)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="preference", to="auth.user")),
            ],
        ),
        migrations.CreateModel(
            name="UserTelegramSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bot_token", models.TextField(blank=True, default="")),
                ("openai_api_key", models.TextField(blank=True, default="")),
                ("admins", models.CharField(blank=True, default="", max_length=500)),
                ("webapp_url", models.CharField(blank=True, default="", max_length=500)),
                ("service_account_token", models.TextField(blank=True, default="")),
                ("backend_api_url", models.CharField(blank=True, default="", max_length=500)),
                ("schedule_check_interval_seconds", models.PositiveIntegerField(default=10)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="telegram_settings", to="auth.user")),
            ],
        ),
    ]

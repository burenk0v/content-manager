from auth_app.models import THEME_CHOICES, get_user_theme


def theme_context(request):
    return {
        'current_theme': get_user_theme(request.user),
        'theme_options': THEME_CHOICES,
    }

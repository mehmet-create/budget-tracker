from django.conf import settings
from .models import UserProfile


def currency_symbol(request):
    """
    Pushes CUSTOM_CURRENCY_SYMBOL and AVAILABLE_CURRENCIES into every template.
    """
    default_symbol = getattr(settings, 'CUSTOM_CURRENCY_SYMBOL', '₦')
    available = getattr(settings, 'AVAILABLE_CURRENCIES', {})

    if not request.user.is_authenticated:
        return {
            'CUSTOM_CURRENCY_SYMBOL': default_symbol,
            'AVAILABLE_CURRENCIES': available,
        }

    # Session cache hit — no DB query needed
    cached = request.session.get('currency_symbol')
    if cached:
        return {
            'CUSTOM_CURRENCY_SYMBOL': cached,
            'AVAILABLE_CURRENCIES': available,
        }

    # Session miss — read from DB and cache the result
    try:
        profile = request.user.userprofile
        symbol = available.get(profile.currency_code, default_symbol)
    except UserProfile.DoesNotExist:
        UserProfile.objects.get_or_create(user=request.user)
        symbol = default_symbol

    request.session['currency_symbol'] = symbol

    return {
        'CUSTOM_CURRENCY_SYMBOL': symbol,
        'AVAILABLE_CURRENCIES': available,
    }
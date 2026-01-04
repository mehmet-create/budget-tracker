from django.conf import settings
from .models import UserProfile

def currency_symbol(request):
    default_symbol = getattr(settings, 'CUSTOM_CURRENCY_SYMBOL', '₦')

    final_symbol = default_symbol
    if request.user.is_authenticated:
        try:
            profile = request.user.userprofile
            persistent_code = profile.currency_code
            final_symbol = settings.AVAILABLE_CURRENCIES.get(persistent_code, default_symbol)

            if request.session.get('currency_symbol') != final_symbol:
                request.session['currency_symbol'] = final_symbol
                 
        except UserProfile.DoesNotExist:
            UserProfile.objects.get_or_create(user=request.user)
    
    return {
        'CUSTOM_CURRENCY_SYMBOL': final_symbol, 
        'AVAILABLE_CURRENCIES': getattr(settings, 'AVAILABLE_CURRENCIES', {}),
    }
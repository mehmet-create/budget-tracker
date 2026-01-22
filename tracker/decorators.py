from django.shortcuts import redirect
def redirect_if_unverified(view_func):
    def wrapper(request, *args, **kwargs):
        if request.session.get('unverified_user_id'):
            return redirect('verify_registration')
        return view_func(request, *args, **kwargs)
    return wrapper
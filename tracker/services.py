import random
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model, aauthenticate
from django.db import transaction
from asgiref.sync import sync_to_async
from .models import UserProfile
from .schemas import * 
from django.utils.crypto import get_random_string

User = get_user_model()

class ServiceError(Exception):
    pass

class PermissionError(ServiceError):
    pass

async def register_user(dto):
    # 1. Check if user exists (Double check for safety)
    if await sync_to_async(User.objects.filter(email=dto.email).exists)():
        raise ServiceError("Email already registered.")
    if await sync_to_async(User.objects.filter(username=dto.username).exists)():
        raise ServiceError("Username taken.")

    # 2. Create the User
    try:
        user = await sync_to_async(User.objects.create_user)(
            username=dto.username,
            email=dto.email,
            password=dto.password
        )
        user.is_active = False
        await sync_to_async(user.save)()

        # --- THE FIX IS HERE ---
        # Instead of .create(), use .get_or_create() to prevent duplicates
        profile, created = await sync_to_async(UserProfile.objects.get_or_create)(user=user)
        
        # 3. Generate Verification Code
        code = get_random_string(6, allowed_chars='0123456789')
        profile.email_verification_code = code
        profile.code_generated_at = timezone.now()
        await sync_to_async(profile.save)()

        return user, code

    except Exception as e:
        # Cleanup if something fails partially
        if 'user' in locals() and user.pk:
            await sync_to_async(user.delete)()
        raise ServiceError(f"Registration failed: {str(e)}")

async def login_service(request, data: LoginDTO):
    user = await aauthenticate(request, username=data.username, password=data.password)
    if user:
        return user, "success"

    try:
        potential_user = await User.objects.select_related('userprofile').aget(username=data.username)
        is_valid = await sync_to_async(potential_user.check_password)(data.password)
        
        if is_valid and not potential_user.is_active:
            return potential_user, "unverified"
    except User.DoesNotExist:
        pass
    return None, "invalid"

async def verify_code(data: VerifyCodeDTO, acting_user_id: int = None):
    if acting_user_id and acting_user_id != data.user_id:
        raise PermissionError("Security Alert: Authorization failed.")

    try:
        user = await User.objects.select_related('userprofile').aget(id=data.user_id)
        profile = user.userprofile
        
        if not profile.email_verification_code:
            raise ServiceError("No verification pending.")
        if data.code != profile.email_verification_code:
            return False, "Invalid verification code."

        user.is_active = True
        await user.asave()
        
        profile.email_verification_code = None
        profile.resend_count = 0
        profile.cooldown_until = None
        await profile.asave()
        return True, "Account verified."
    except User.DoesNotExist:
        raise ServiceError("User not found.")

async def resend_code(data: ResendCodeDTO):
    try:
        user = await User.objects.select_related('userprofile').aget(id=data.user_id)
        profile = user.userprofile
        now = timezone.now()

        if profile.cooldown_until and now < profile.cooldown_until:
            wait = int((profile.cooldown_until - now).total_seconds())
            raise ServiceError(f"Please wait {wait} seconds.")

        @sync_to_async
        def generate(p):
            p.resend_count += 1
            next_cooldown = 1 if p.resend_count <= 3 else 5 * (2**(p.resend_count - 4))
            p.cooldown_until = timezone.now() + timedelta(minutes=min(next_cooldown, 1440))
            code = str(random.randint(100000, 999999))
            p.email_verification_code = code
            p.save()
            return code
        
        new_code = await generate(profile)
        return True, new_code, user.email
    except User.DoesNotExist:
        raise ServiceError("User not found.")

async def request_email_change(data: EmailChangeRequestDTO):
    if await User.objects.filter(email=data.new_email).exclude(id=data.user_id).aexists():
        raise ServiceError("This email is already in use.")

    user = await User.objects.select_related('userprofile').aget(id=data.user_id)
    profile = user.userprofile
    
    if profile.last_email_change:
        if timezone.now() < (profile.last_email_change + timedelta(days=2)):
             raise ServiceError("You can only change your email once every 48 hours.")

    code = str(random.randint(100000, 999999))
    profile.email_verification_code = code
    profile.pending_email = data.new_email
    profile.code_generated_at = timezone.now()
    await profile.asave()
    return code

async def verify_email_change(data: VerifyEmailChangeDTO):
    user = await User.objects.select_related('userprofile').aget(id=data.user_id)
    profile = user.userprofile
    
    if not profile.pending_email or not profile.email_verification_code:
         raise ServiceError("No active request.")
         
    if data.code != profile.email_verification_code:
        return False, "Invalid code."

    user.email = profile.pending_email
    await user.asave()
    
    profile.last_email_change = timezone.now()
    profile.email_verification_code = None
    profile.pending_email = None
    await profile.asave()
    return True, "Email updated."

async def change_password(user, data: PasswordChangeDTO):
    is_correct = await sync_to_async(user.check_password)(data.old_password)
    if not is_correct:
        raise ServiceError("Old password incorrect.")

    @sync_to_async
    def set_pass(u, p):
        u.set_password(p)
        u.save()
    await set_pass(user, data.new_password)
    return True, "Password changed."

async def delete_account(data: DeleteAccountDTO):
    user = await User.objects.aget(id=data.user_id)
    is_correct = await sync_to_async(user.check_password)(data.password)
    if not is_correct:
        raise ServiceError("Incorrect password.")
    await user.adelete()
    return True, "Account deleted."

async def update_user_location(user_id: int, data: UpdateLocationDTO):
    user = await User.objects.select_related('userprofile').aget(id=user_id)
    profile = user.userprofile
    profile.last_latitude = data.latitude
    profile.last_longitude = data.longitude
    profile.location_updated_at = timezone.now()
    await profile.asave()
    return True, "Location updated."
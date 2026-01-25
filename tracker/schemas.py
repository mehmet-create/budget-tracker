from pydantic import BaseModel, EmailStr, Field

class RegisterDTO(BaseModel):
    username: str = Field(..., min_length=3, max_length=150)
    email: EmailStr
    password: str = Field(..., min_length=8)

class LoginDTO(BaseModel):
    username: str
    password: str

class VerifyCodeDTO(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)
    user_id: int

class ResendCodeDTO(BaseModel):
    user_id: int

class EmailChangeRequestDTO(BaseModel):
    user_id: int
    new_email: EmailStr

class VerifyEmailChangeDTO(BaseModel):
    user_id: int
    code: str = Field(..., min_length=6, max_length=6)

class PasswordChangeDTO(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)

class DeleteAccountDTO(BaseModel):
    user_id: int
    password: str = Field(..., min_length=1)

class UpdateLocationDTO(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
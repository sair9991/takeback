from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters")
    chess_com_username: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UpdateProfileRequest(BaseModel):
    chess_com_username: Optional[str] = None
    lichess_username: Optional[str] = None


class UserResponse(BaseModel):
    user_id: str
    email: Optional[str] = None
    chess_com_username: Optional[str] = None
    lichess_username: Optional[str] = None
    created_at: Optional[datetime] = None


class AuthSuccessResponse(BaseModel):
    status: str = "ok"
    user: UserResponse

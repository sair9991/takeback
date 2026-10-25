from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, description="Email or username")
    password: str = Field(..., min_length=3, description="Password must be at least 3 characters")
    chess_com_username: Optional[str] = None


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, description="Email or username")
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
    token: Optional[str] = None

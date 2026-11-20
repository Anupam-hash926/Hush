from pydantic import BaseModel, Field
from typing import Literal

class UserCreate(BaseModel):
    email:str
    password:str

class UserLogin(BaseModel):
    email:str
    password:str

class Token(BaseModel):
    access_token:str
    token_type:str

class ProjectCreate(BaseModel):
    name:str
    description:str|None=None

class ProjectMember(BaseModel):
     target_email:str
     role:Literal["viewer", "editor"] = "viewer"
class SecretCreate(BaseModel):
    key_name: str
    secret_value: str
    quorum_size: int = Field(default=1, ge=1)
    access_window_hours: int = Field(default=24, ge=1)
    max_views: int = Field(default=1, ge=1)
class SecretResponse(BaseModel):
    id:str
    key_name:str
class ApprovalRequest(BaseModel):
    target_email: str
    approval_validity_seconds: int = Field(default=86400, ge=1)
    request_id: str | None = None
class ReviewerAssign(BaseModel):
    target_email: str
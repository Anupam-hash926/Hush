from pydantic import BaseModel
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
    quorum_size:int=1
    access_window_hours:int=24
    max_views:int=1
class SecretResponse(BaseModel):
    id:str
    key_name:str
class ApprovalRequest(BaseModel):
    target_email:str
from fastapi import FastAPI
from app.security import get_password_hash
from app.schemas import UserCreate

app=FastAPI(title="Hush API")
@app.get("/")
async def root():
    return{"message":"Hush is up and running!"}
@app.post("/register")
async def register_user(user:UserCreate):
    hashed_pw=get_password_hash(user.password)

    return{
        "email":user.email,
        "original_password":user.password,
        "secure_hash":hashed_pw
    }


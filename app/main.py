from fastapi import FastAPI, HTTPException
from app.security import get_password_hash
from app.schemas import UserCreate
from app.crud import create_user_in_db

app = FastAPI(title="Hush API")

@app.get("/")
async def root():
    return {"message": "Hush is up and running!"}

@app.post("/register")
async def register_user(user: UserCreate):
    hashed_pw = get_password_hash(user.password)
    created_email = create_user_in_db(user.email, hashed_pw)
    
    if not created_email:
        raise HTTPException(status_code=400, detail="User already exists")
        
    return {"message": "User registered successfully", "email": created_email}
from fastapi import FastAPI, HTTPException, Depends
from app.security import get_password_hash, verify_password, create_access_token, get_current_user
from app.schemas import UserCreate, UserLogin, Token
from app.crud import create_user_in_db, get_user_by_email

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

@app.post("/login", response_model=Token)
async def login(user: UserLogin):
    password_hash = get_user_by_email(user.email)
    
    if not password_hash or not verify_password(user.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
        
    token = create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me")
async def read_current_user(current_user: str = Depends(get_current_user)):
    return {"message": "You are authenticated!", "user": current_user}